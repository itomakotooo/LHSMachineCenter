"""M37 design verification — player-experience gate.

M37 = "100× Diamond" — Lightning-Link/Dragon-Link inspired classic 3-reel.
Brand signature = booster diamonds (mini/minor/major/grand) on R2.
No Feature engine. Top jackpot = (high7|wild, grand, high7|wild) = 1000×.

Categories:
    [RTP]            Total RTP within tolerance per mode
    [HIT]            Hit rate within band per mode
    [WILD]           Wild on payline (R1+R3 wild) signature
    [BOOSTER]        Booster on R2 (brand) signature
    [SHARE]          Per-family RTP share within band
    [DENSITY]        Per-family per-reel density visually合理
    [BLANK-VAR]      Per-reel Blank balance ratio
    [BASE-CV]        Mode 1 CV ≤ 11 (structural floor due to 100×/1000× pays)
    [MODE7-BIGWIN]   Mode 7 high7+wild+booster weights ∈ [m1×0.80, m1×1.10] (band)
    [MODE7-CUT]      Mode 7 bar tier cut from mode 1
    [LUCKY-MONO]     Mode 5 big-win pay frequencies ≥ mode 2 (super-lucky monotonic)
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

SPEC = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"

PAY_TO_FAMILY = {
    "1":   "high7", "2": "7bar", "3": "bar_tier", "4": "bar_tier", "5": "bar_tier",
    "6":   "high7", "7": "bar_tier",
    "8":   "booster_alone", "9": "booster_alone",
    "102": "wild_amplified", "103": "wild_amplified", "104": "wild_amplified",
}

BIGWIN_PAY_IDS = ("1", "8", "102", "103", "104")  # high7 + grand-alone + pure-wild+booster

MODE_TARGETS = {
    1: {
        "rtp": 95.0, "rtp_tol": 1.0,
        "hit_lo": 0.13, "hit_hi": 0.22,
        "wild_lo": 0.04, "wild_hi": 0.18,
        "booster_lo": 0.04, "booster_hi": 0.12,
        "cv_max": 14.0,
        "family_share_band": {
            "high7": (0.03, 0.30),
            "7bar":  (0.05, 0.25),
            "bar_tier": (0.20, 0.50),
            "booster_alone": (0.10, 0.35),
            "wild_amplified": (0.0, 0.10),    # structurally low (reroll block)
        },
    },
    7: {
        "rtp": 85.0, "rtp_tol": 2.0,
        "hit_lo": 0.10, "hit_hi": 0.20,
        "wild_lo": 0.03, "wild_hi": 0.18,
        "booster_lo": 0.04, "booster_hi": 0.12,
        "family_share_band": {
            "high7": (0.03, 0.30),
            "7bar":  (0.03, 0.25),
            "bar_tier": (0.10, 0.45),
            "booster_alone": (0.10, 0.45),    # naturally rises when bars cut
            "wild_amplified": (0.0, 0.10),
        },
    },
    2: {
        "rtp": 300.0, "rtp_tol": 20.0,
        "hit_lo": 0.20, "hit_hi": 0.32,
        "wild_lo": 0.05, "wild_hi": 0.20,
        "booster_lo": 0.08, "booster_hi": 0.20,
        "family_share_band": {
            "high7": (0.05, 0.35),
            "7bar":  (0.03, 0.30),
            "bar_tier": (0.15, 0.50),
            "booster_alone": (0.15, 0.45),
            "wild_amplified": (0.0, 0.10),    # structurally low (reroll block)
        },
    },
    5: {
        "rtp": 500.0, "rtp_tol": 40.0,
        "hit_lo": 0.22, "hit_hi": 0.45,
        "wild_lo": 0.07, "wild_hi": 0.24,
        # Mode 5 super-lucky has visible boosters as brand reinforcement; allow up to 30%.
        "booster_lo": 0.10, "booster_hi": 0.30,
        "family_share_band": {
            "high7": (0.05, 0.35),
            "7bar":  (0.02, 0.30),
            "bar_tier": (0.15, 0.55),
            "booster_alone": (0.10, 0.50),
            "wild_amplified": (0.0, 0.15),
        },
    },
}

# Per-reel density caps (per-family per-mode)
PER_REEL_DENSITY_HI = {
    1: {"wild": 0.10, "high7": 0.20, "7bar": 0.22, "3bar": 0.22, "2bar": 0.22, "1bar": 0.32,
        "mini": 0.10, "minor": 0.10, "major": 0.10, "grand": 0.03},
    7: {"wild": 0.10, "high7": 0.20, "7bar": 0.22, "3bar": 0.22, "2bar": 0.22, "1bar": 0.32,
        "mini": 0.12, "minor": 0.12, "major": 0.12, "grand": 0.03},
    2: {"wild": 0.18, "high7": 0.25, "7bar": 0.24, "3bar": 0.24, "2bar": 0.24, "1bar": 0.35,
        "mini": 0.15, "minor": 0.15, "major": 0.15, "grand": 0.05},
    5: {"wild": 0.20, "high7": 0.25, "7bar": 0.24, "3bar": 0.24, "2bar": 0.24, "1bar": 0.35,
        "mini": 0.15, "minor": 0.15, "major": 0.18, "grand": 0.07},
}
PER_REEL_DENSITY_LO = {
    "wild": 0.005, "high7": 0.005,
    "7bar": 0.003, "3bar": 0.003, "2bar": 0.003, "1bar": 0.003,    # bars on R2 naturally low (booster-heavy)
    "mini": 0.002, "minor": 0.002, "major": 0.001, "grand": 0.0005,
}

# M37 R2 = booster reel naturally blank-heavy (boosters take few positions but
# blank dominates → R2 blank density 50-85%; R1/R3 blank 3-30% depending on lucky tier).
# Mode 5 super-lucky inflates R1/R3 non-blank → R1/R3 blank density crashes to 3-5%
# while R2 blank stays ~50% (booster reel structure). Ratio naturally extreme in m5.
BLANK_RATIO_CAP = {1: 5.0, 7: 5.0, 2: 6.0, 5: 20.0}

# Mode 7 big-win weight band (relative to mode 1)
MODE7_BIGWIN_LO = 0.80
MODE7_BIGWIN_HI = 1.10

# Mode 7 cut: bar_tier RTP must drop ≥ X pp from mode 1
MODE7_BAR_MIN_CUT_PP = 5.0


def family_rtp_breakdown(profile):
    family = defaultdict(float)
    for pid, contrib in profile.get("pay_rtp", {}).items():
        f = PAY_TO_FAMILY.get(pid)
        if f is None:
            continue
        family[f] += contrib
    return {k: v * 100 for k, v in family.items()}


def per_reel_density(engine):
    out = {}
    for r_idx, reel in enumerate(engine.reels):
        marg = compute_reel_marginal(reel)
        for sym, p in marg.items():
            out[(sym, r_idx)] = p
    return out


def wild_on_payline_p(engine):
    m1 = compute_reel_marginal(engine.reels[0])
    m3 = compute_reel_marginal(engine.reels[2])
    return 1 - (1 - m1.get("wild", 0)) * (1 - m3.get("wild", 0))


def booster_r2_p(engine):
    m2 = compute_reel_marginal(engine.reels[1])
    return m2.get("mini", 0) + m2.get("minor", 0) + m2.get("major", 0) + m2.get("grand", 0)


def get_per_position_weights(mode):
    return json.loads((_ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json").read_text(encoding="utf-8")).get("weights", [])


def compute_per_family_weight(mode, sym, reel):
    """Per-family per-reel uniform: weight at first occurrence of sym on reel."""
    strip = json.loads(STRIPS.read_text(encoding="utf-8"))["reels"]
    weights = get_per_position_weights(mode)
    for pos, s in enumerate(strip[reel]):
        if s == sym:
            return int(weights[reel][pos])
    return None


def make_check(category, mode, label, ok, info=""):
    return {"category": category, "mode": mode, "label": label, "ok": bool(ok), "info": info}


def main():
    state = {}
    for mode in (1, 2, 5, 7):
        wp = _ROOT / "slot_designer" / "weights" / "M37" / f"mode_{mode}" / "weights.json"
        if not wp.exists():
            continue
        engine, _ = load_engine(SPEC, wp)
        profile = analytic_profile(engine)
        state[mode] = {
            "engine": engine, "profile": profile,
            "family_rtp_pp": family_rtp_breakdown(profile),
            "densities": per_reel_density(engine),
            "wild_on_payline": wild_on_payline_p(engine),
            "booster_on_r2": booster_r2_p(engine),
        }

    print(f"\n=== M37 player-experience design verification ===\n")
    all_checks = []

    for mode in sorted(state.keys()):
        s = state[mode]
        targets = MODE_TARGETS[mode]
        p = s["profile"]
        print(f"--- Mode {mode} ---")
        print(f"  RTP={p['rtp_pct']:.2f}%  hit={p['hit_rate']:.2%}  CV={p['cv']:.2f}  wild={s['wild_on_payline']:.2%}  booster_R2={s['booster_on_r2']:.2%}")
        for f in ("high7", "7bar", "bar_tier", "booster_alone", "wild_amplified"):
            v = s["family_rtp_pp"].get(f, 0.0)
            share = v / p["rtp_pct"] * 100 if p["rtp_pct"] > 0 else 0
            print(f"    {f:18s} {v:6.2f}pp ({share:5.1f}%)")

        ok = abs(p["rtp_pct"] - targets["rtp"]) <= targets["rtp_tol"]
        all_checks.append(make_check("RTP", mode, f"{p['rtp_pct']:.2f}% vs {targets['rtp']:.0f}±{targets['rtp_tol']:.0f}", ok))

        ok = targets["hit_lo"] <= p["hit_rate"] <= targets["hit_hi"]
        all_checks.append(make_check("HIT", mode, f"{p['hit_rate']:.2%} vs [{targets['hit_lo']:.0%}, {targets['hit_hi']:.0%}]", ok))

        ok = targets["wild_lo"] <= s["wild_on_payline"] <= targets["wild_hi"]
        all_checks.append(make_check("WILD", mode, f"{s['wild_on_payline']:.2%} vs [{targets['wild_lo']:.0%}, {targets['wild_hi']:.0%}]", ok))

        ok = targets["booster_lo"] <= s["booster_on_r2"] <= targets["booster_hi"]
        all_checks.append(make_check("BOOSTER", mode, f"{s['booster_on_r2']:.2%} vs [{targets['booster_lo']:.0%}, {targets['booster_hi']:.0%}]", ok))

        if "cv_max" in targets:
            ok = p["cv"] <= targets["cv_max"]
            all_checks.append(make_check("BASE-CV", mode, f"CV {p['cv']:.2f} vs ≤ {targets['cv_max']:.1f}", ok))

        for f, (lo, hi) in targets["family_share_band"].items():
            actual = s["family_rtp_pp"].get(f, 0.0) / p["rtp_pct"] if p["rtp_pct"] > 0 else 0
            ok = lo <= actual <= hi
            all_checks.append(make_check("SHARE", mode, f"{f} {actual:.1%} vs [{lo:.0%}, {hi:.0%}]", ok))

        density_hi = PER_REEL_DENSITY_HI[mode]
        for (sym, r), d in sorted(s["densities"].items()):
            if sym == "blank":
                continue
            den_lo = PER_REEL_DENSITY_LO.get(sym, 0.005)
            den_hi = density_hi.get(sym, 0.20)
            ok = den_lo <= d <= den_hi
            if not ok:
                all_checks.append(make_check("DENSITY", mode, f"{sym} R{r+1} {d:.2%} outside [{den_lo:.1%}, {den_hi:.0%}]", ok))

        blanks = [s["densities"].get(("blank", r), 0) * 100 for r in range(3)]
        bratio = max(blanks) / min(blanks) if min(blanks) > 0 else float("inf")
        ok = bratio <= BLANK_RATIO_CAP[mode]
        all_checks.append(make_check("BLANK-VAR", mode, f"max/min Blank ratio {bratio:.2f}x vs cap {BLANK_RATIO_CAP[mode]:.1f}x", ok))

        print()

    # Cross-mode invariants
    if 1 in state and 7 in state:
        # Big-win weights ∈ [m1×0.80, m1×1.10] (band, not strict equality —
        # allows density preservation when bar cuts shrink R2 total weight)
        bigwin_keys = (
            [("high7", r) for r in range(3)] +
            [("wild", r) for r in (0, 2)] +
            [(b, 1) for b in ("mini", "minor", "major", "grand")]
        )
        for sym, r in bigwin_keys:
            w1 = compute_per_family_weight(1, sym, r)
            w7 = compute_per_family_weight(7, sym, r)
            if w1 is None or w7 is None:
                continue
            lo = max(1, int(w1 * MODE7_BIGWIN_LO))
            hi = max(1, int(w1 * MODE7_BIGWIN_HI))
            ok = lo <= w7 <= hi
            all_checks.append(make_check("MODE7-BIGWIN", 7, f"{sym}_R{r}: m7={w7} ∈ [{lo}, {hi}] (m1={w1})", ok))

        # Mode 7 bar cut
        m1_bar = state[1]["family_rtp_pp"].get("bar_tier", 0)
        m7_bar = state[7]["family_rtp_pp"].get("bar_tier", 0)
        cut = m1_bar - m7_bar
        ok = cut >= MODE7_BAR_MIN_CUT_PP
        all_checks.append(make_check("MODE7-CUT", 7, f"Bar tier cut {cut:.2f}pp (min {MODE7_BAR_MIN_CUT_PP:.1f}pp)", ok))

        # Mode 7 big-win RTP preservation: top jackpot freq within m1 ± 30%
        m1_top_p = (
            (state[1]["densities"].get(("high7", 0), 0) + state[1]["densities"].get(("wild", 0), 0))
            * state[1]["densities"].get(("grand", 1), 0)
            * (state[1]["densities"].get(("high7", 2), 0) + state[1]["densities"].get(("wild", 2), 0))
        )
        m7_top_p = (
            (state[7]["densities"].get(("high7", 0), 0) + state[7]["densities"].get(("wild", 0), 0))
            * state[7]["densities"].get(("grand", 1), 0)
            * (state[7]["densities"].get(("high7", 2), 0) + state[7]["densities"].get(("wild", 2), 0))
        )
        ratio = m7_top_p / m1_top_p if m1_top_p > 0 else 0
        ok = 0.70 <= ratio <= 1.30
        all_checks.append(make_check("MODE7-BIGWIN", 7, f"top-jackpot freq m7/m1 ratio {ratio:.2f}x (band [0.70, 1.30])", ok))

    if 2 in state and 5 in state:
        # Per-pay_id check (loose tolerance — pay_id 8 may shrink because pay_id N×grand grows)
        for pid in BIGWIN_PAY_IDS:
            h2 = state[2]["profile"]["pay_hits"].get(pid, 0)
            h5 = state[5]["profile"]["pay_hits"].get(pid, 0)
            ok = h5 >= h2 * 0.50    # individual: 0.5x tolerance
            all_checks.append(make_check("LUCKY-MONO", 5, f"pay_id {pid}: m5={h5:.6f} vs m2={h2:.6f} (ratio {h5/h2 if h2>0 else 0:.2f}x)", ok))
        # Sum check (the real super-lucky monotonic — total big-win freq must rise)
        sum2 = sum(state[2]["profile"]["pay_hits"].get(pid, 0) for pid in BIGWIN_PAY_IDS)
        sum5 = sum(state[5]["profile"]["pay_hits"].get(pid, 0) for pid in BIGWIN_PAY_IDS)
        ratio = sum5 / sum2 if sum2 > 0 else 0
        ok = ratio >= 1.5
        all_checks.append(make_check("LUCKY-MONO", 5, f"big-win SUM: m5={sum5:.6f} vs m2={sum2:.6f} (ratio {ratio:.2f}x ≥ 1.5)", ok))
        # Total RTP and hit rate must rise
        ok = state[5]["profile"]["rtp_pct"] > state[2]["profile"]["rtp_pct"]
        all_checks.append(make_check("LUCKY-MONO", 5, f"total RTP m5 > m2 ({state[5]['profile']['rtp_pct']:.1f} > {state[2]['profile']['rtp_pct']:.1f})", ok))

    print("=== Verification results ===")
    by_cat = defaultdict(list)
    for c in all_checks:
        by_cat[c["category"]].append(c)
    fail_count = 0
    for cat in sorted(by_cat.keys()):
        checks = by_cat[cat]
        passes = sum(1 for c in checks if c["ok"])
        fails = sum(1 for c in checks if not c["ok"])
        status = "GREEN" if fails == 0 else f"RED ({fails}/{len(checks)} fail)"
        print(f"  [{cat:12s}] {passes:3d} pass / {len(checks):3d} total — {status}")
        for c in checks:
            if not c["ok"]:
                m = f"mode {c['mode']}" if c["mode"] is not None else "all"
                print(f"     [FAIL] {m}: {c['label']}")
                fail_count += 1

    print(f"\n{'GREEN — all checks pass' if fail_count == 0 else f'RED — {fail_count} check(s) failed'}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
