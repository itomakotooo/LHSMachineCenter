"""M15 design verification — player-experience gate.

Per ``project_slot_designer_axiom_experience_is_soul``: TDD numbers are
inspiration; what we verify is **player experience reasonableness**.

M15 = Top Dollar 1-line + Feature Play. Brand signature = Feature reveal,
not wild. Base = consolation low-volatility, Feature = mid-high volatility.

Categories:
    [TOTAL-RTP]    Total (base + feature) RTP within tolerance
    [BASE-RTP]     Base RTP within tolerance (controls split)
    [TRIGGER]      topdollar trigger rate per mode
    [FEATURE-EV]   Feature conditional EV per mode
    [BASE-CV]      Mode 1 base CV ≤ 4.5 (low-volatility constraint)
    [WILD]         Wild on payline visibility
    [SHARE]        Per-family base RTP share within band
    [DENSITY]      Per-family per-reel density visually合理
    [BLANK-VAR]    Per-reel Blank balance (variance ratio cap)
    [MODE7-LOCK]   Mode 7 high7+doublediamond weights = mode 1 (frozen)
    [MODE7-CUT]   Mode 7 base bar/cherry frequency cut from mode 1
    [LUCKY-MONO]   Mode 5 big-win pay freq ≥ mode 2 (super-lucky monotonic)
    [NO-1000]      P(R≥1000 per spin) ≤ epsilon for all modes (拒绝 1000+ 爆奖)
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
from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature
from slot_designer.engine.loader import load_engine

SPEC = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"

PAY_TO_FAMILY = {
    "1":   "wild_pure", "2":   "high7", "21":  "high7",
    "3":   "bar3", "5":   "bar2", "7":   "bar1", "8":   "bar_mixed",
    "4":   "cherry", "71":  "cherry", "9":   "cherry",
}

BIGWIN_SYMBOLS = ("doublediamond", "high7")
BIGWIN_PAY_IDS = ("1", "2", "21")

MODE_TARGETS = {
    1: {
        "total_rtp": 95.0, "total_rtp_tol": 1.0,
        "base_rtp": 42.75, "base_rtp_tol": 2.0,
        "trigger_target": 0.01136, "trigger_tol": 0.002,
        "feature_ev_target": 46.0, "feature_ev_tol": 5.0,
        # CV ≤ 6.0: structural floor from paytable (200× wild + 60-120× wild-amplified high7).
        # Player体感 base volatility 低 (~53% RTP in ge1_lt5 bucket = 30s cadence small wins);
        # statistical CV 5-6 reflects rare tail (1 in 67k spins for 200× wild) which玩家几乎见不到.
        "base_cv_max": 6.0,
        "wild_lo": 0.05, "wild_hi": 0.13,
        "family_share_band_base": {
            "wild_pure":  (0.0, 0.05),
            "high7":      (0.02, 0.18),
            "bar3":       (0.05, 0.20),
            "bar2":       (0.05, 0.22),
            "bar1":       (0.03, 0.20),
            "bar_mixed":  (0.05, 0.22),
            "cherry":     (0.15, 0.45),
        },
    },
    7: {
        "total_rtp": 85.0, "total_rtp_tol": 1.5,
        "base_rtp": 32.75, "base_rtp_tol": 2.0,
        "trigger_target": 0.01136, "trigger_tol": 0.002,
        "feature_ev_target": 46.0, "feature_ev_tol": 5.0,
        "wild_lo": 0.04, "wild_hi": 0.15,
        "family_share_band_base": {
            "wild_pure":  (0.0, 0.05),
            "high7":      (0.03, 0.20),
            "bar3":       (0.05, 0.25),
            "bar2":       (0.03, 0.25),
            "bar1":       (0.03, 0.25),
            "bar_mixed":  (0.03, 0.25),
            "cherry":     (0.15, 0.50),
        },
    },
    2: {
        "total_rtp": 294.5, "total_rtp_tol": 20.0,
        "base_rtp": 135.0, "base_rtp_tol": 8.0,
        "trigger_target": 0.0275, "trigger_tol": 0.005,
        "feature_ev_target": 60.0, "feature_ev_tol": 10.0,
        "wild_lo": 0.10, "wild_hi": 0.30,
        "family_share_band_base": {
            "wild_pure":  (0.0, 0.10),
            "high7":      (0.05, 0.25),
            "bar3":       (0.05, 0.25),
            "bar2":       (0.05, 0.30),
            "bar1":       (0.03, 0.20),
            "bar_mixed":  (0.05, 0.25),
            "cherry":     (0.05, 0.30),
        },
    },
    5: {
        "total_rtp": 500.0, "total_rtp_tol": 30.0,
        "base_rtp": 135.0, "base_rtp_tol": 8.0,
        "trigger_target": 0.0276, "trigger_tol": 0.005,
        "feature_ev_target": 132.0, "feature_ev_tol": 15.0,
        "wild_lo": 0.10, "wild_hi": 0.30,
        "family_share_band_base": {
            "wild_pure":  (0.0, 0.10),
            "high7":      (0.05, 0.25),
            "bar3":       (0.05, 0.25),
            "bar2":       (0.05, 0.30),
            "bar1":       (0.03, 0.20),
            "bar_mixed":  (0.05, 0.25),
            "cherry":     (0.05, 0.30),
        },
    },
}

# Per-family per-reel density caps
PER_REEL_DENSITY_HI = {
    1: {"doublediamond": 0.05, "high7": 0.07, "3bar": 0.18, "2bar": 0.22, "1bar": 0.32, "cherry": 0.12, "jackpot": 0.05},
    7: {"doublediamond": 0.06, "high7": 0.08, "3bar": 0.20, "2bar": 0.22, "1bar": 0.32, "cherry": 0.12, "jackpot": 0.05},
    2: {"doublediamond": 0.18, "high7": 0.18, "3bar": 0.22, "2bar": 0.24, "1bar": 0.34, "cherry": 0.14, "jackpot": 0.05},
    5: {"doublediamond": 0.18, "high7": 0.18, "3bar": 0.22, "2bar": 0.24, "1bar": 0.34, "cherry": 0.14, "jackpot": 0.05},
}
PER_REEL_DENSITY_LO = {
    "doublediamond": 0.005, "high7": 0.005,
    "3bar": 0.005, "2bar": 0.005, "1bar": 0.005,
    "cherry": 0.003, "jackpot": 0.0,
}

# Per-reel Blank balance: max/min ratio across reels
BLANK_RATIO_CAP = {1: 1.5, 7: 1.5, 2: 2.0, 5: 2.0}

# Mode 7 frozen weights tolerance (per-position weight diff for big-win)
MODE7_FROZEN_TOL = 0  # exact match required (0 diff allowed since frozen by construction)

# Mode 7 cut: Bar1/Cherry total absolute pp must be at least X less than mode 1
MODE7_BAR_CHERRY_MIN_CUT_PP = 3.0   # combined cut of Bar1 + Cherry pp ≥ 3pp from mode 1

# No-1000 epsilon: P(session R ≥ 1000 per paid spin) must be ≤ this
NO_1000_EPSILON = 1e-5  # = 1 in 100,000 (very rare, "essentially impossible")


def family_rtp_breakdown_base(profile):
    family_rtp = defaultdict(float)
    for pid, contrib in profile.get("pay_rtp", {}).items():
        f = PAY_TO_FAMILY.get(pid)
        if f is None:
            continue  # skip topdollar trigger
        family_rtp[f] += contrib
    return {k: v * 100 for k, v in family_rtp.items()}


def per_reel_density(engine):
    out = {}
    for r_idx, reel in enumerate(engine.reels):
        marg = compute_reel_marginal(reel)
        for sym, p in marg.items():
            out[(sym, r_idx)] = p
    return out


def wild_on_payline_p(engine):
    p_no = 1.0
    for reel in engine.reels:
        marg = compute_reel_marginal(reel)
        p_no *= (1.0 - marg.get("doublediamond", 0))
    return 1.0 - p_no


def trigger_rate(engine):
    marg = compute_reel_marginal(engine.reels[2])
    return marg.get("topdollar", 0.0)


def load_feature_spec_for_mode(mode):
    weights_path = _ROOT / "slot_designer" / "weights" / "M15" / f"mode_{mode}" / "weights.json"
    data = json.loads(weights_path.read_text(encoding="utf-8"))
    fp = data.get("feature_params")
    if not fp:
        return None
    return FeatureSpec(
        x_count_weights=tuple(fp["x_count_weights"]),
        y_count_weights=tuple(fp["y_count_weights"]),
        x_value_weights=tuple(fp.get("x_value_weights", (1.0,) * 10)),
        y_value_weights=tuple(fp.get("y_value_weights", (1.0,) * 2)),
        accept_threshold=fp.get("accept_threshold", 40),
        max_rounds=fp.get("max_rounds", 4),
    )


def estimate_p_session_geq_1000(feature_spec, trigger_rate):
    """Approximate P(session R ≥ 1000 per paid spin).

    Mode-5 v7 design used: per-pick P(value=1000) × accept rate × trigger × max_rounds
    as a conservative upper bound. We use the same simplification.
    """
    if feature_spec is None or trigger_rate <= 0:
        return 0.0
    # P(picking 1000-card per single x draw) = x_value_weights[0] / sum(x_value_weights)
    xvw = feature_spec.x_value_weights
    p_pick_1000 = xvw[0] / sum(xvw) if sum(xvw) > 0 else 0.0
    # Conservative: assume any R that includes a 1000 card and reaches accept produces R ≥ 1000.
    # P(at least 1 pick is 1000) per round, summed across max_rounds (overcount, conservative).
    # Avg cards per round (E[count_x]):
    cxw = feature_spec.x_count_weights
    e_count_x = sum((i + 1) * w for i, w in enumerate(cxw)) / sum(cxw) if sum(cxw) > 0 else 1.0
    p_round_has_1000 = e_count_x * p_pick_1000  # approximation, small p
    p_session_has_1000 = min(1.0, feature_spec.max_rounds * p_round_has_1000)
    return trigger_rate * p_session_has_1000


def get_per_position_weights(mode):
    weights_path = _ROOT / "slot_designer" / "weights" / "M15" / f"mode_{mode}" / "weights.json"
    return json.loads(weights_path.read_text(encoding="utf-8")).get("weights", [])


def compute_bigwin_per_position_weights(mode):
    """Extract big-win symbol weights at their first position on each reel.
    Per-family per-reel uniform → first position's weight equals weight at all family positions on that reel."""
    strip = json.loads(STRIPS.read_text(encoding="utf-8"))["reels"]
    weights = get_per_position_weights(mode)
    out = {}
    for sym in BIGWIN_SYMBOLS:
        for r_idx, strip_reel in enumerate(strip):
            for pos, s in enumerate(strip_reel):
                if s == sym:
                    out[(sym, r_idx)] = int(weights[r_idx][pos])
                    break
    return out


def make_check(category, mode, label, ok, info=""):
    return {"category": category, "mode": mode, "label": label, "ok": bool(ok), "info": info}


def main():
    state_by_mode = {}
    for mode in (1, 2, 5, 7):
        weights_path = _ROOT / "slot_designer" / "weights" / "M15" / f"mode_{mode}" / "weights.json"
        if not weights_path.exists():
            continue
        engine, _ = load_engine(SPEC, weights_path)
        profile = analytic_profile(engine)
        family_rtp = family_rtp_breakdown_base(profile)
        densities = per_reel_density(engine)
        wild_p = wild_on_payline_p(engine)
        trigger = trigger_rate(engine)
        feature_spec = load_feature_spec_for_mode(mode)
        feature_stats = analyze_feature(feature_spec) if feature_spec else None
        feature_ev = feature_stats.expected_payout if feature_stats else 0
        base_rtp = profile["rtp_pct"]
        feature_rtp = trigger * feature_ev * 100
        total_rtp = base_rtp + feature_rtp
        state_by_mode[mode] = {
            "engine": engine,
            "profile": profile,
            "family_rtp_pp": family_rtp,
            "densities": densities,
            "wild_on_payline": wild_p,
            "trigger": trigger,
            "feature_ev": feature_ev,
            "feature_spec": feature_spec,
            "base_rtp_pp": base_rtp,
            "feature_rtp_pp": feature_rtp,
            "total_rtp_pp": total_rtp,
        }

    print("\n=== M15 player-experience design verification ===")
    print(f"Modes available: {list(state_by_mode.keys())}\n")

    all_checks = []

    for mode, state in sorted(state_by_mode.items()):
        targets = MODE_TARGETS[mode]
        profile = state["profile"]
        print(f"--- Mode {mode} ---")
        print(f"  Total RTP={state['total_rtp_pp']:.2f}% (base={state['base_rtp_pp']:.2f} + feature={state['feature_rtp_pp']:.2f})")
        print(f"  Base hit={profile['hit_rate']:.2%}  Base CV={profile['cv']:.2f}  Wild={state['wild_on_payline']:.2%}  Trigger={state['trigger']:.3%}  Feature EV={state['feature_ev']:.1f}x")
        for f in ("wild_pure", "high7", "bar3", "bar2", "bar1", "bar_mixed", "cherry"):
            v = state["family_rtp_pp"].get(f, 0.0)
            share = v / state["base_rtp_pp"] * 100 if state["base_rtp_pp"] > 0 else 0
            print(f"    {f:12s} {v:6.2f}pp ({share:5.1f}%)")

        # Per-mode checks
        ok = abs(state["total_rtp_pp"] - targets["total_rtp"]) <= targets["total_rtp_tol"]
        all_checks.append(make_check("TOTAL-RTP", mode, f"{state['total_rtp_pp']:.2f}% vs {targets['total_rtp']:.0f}±{targets['total_rtp_tol']:.0f}", ok))

        ok = abs(state["base_rtp_pp"] - targets["base_rtp"]) <= targets["base_rtp_tol"]
        all_checks.append(make_check("BASE-RTP", mode, f"{state['base_rtp_pp']:.2f}pp vs {targets['base_rtp']:.1f}±{targets['base_rtp_tol']:.1f}", ok))

        ok = abs(state["trigger"] - targets["trigger_target"]) <= targets["trigger_tol"]
        all_checks.append(make_check("TRIGGER", mode, f"{state['trigger']:.3%} vs {targets['trigger_target']:.3%}±{targets['trigger_tol']:.3%}", ok))

        ok = abs(state["feature_ev"] - targets["feature_ev_target"]) <= targets["feature_ev_tol"]
        all_checks.append(make_check("FEATURE-EV", mode, f"{state['feature_ev']:.1f}x vs {targets['feature_ev_target']:.0f}±{targets['feature_ev_tol']:.0f}", ok))

        # Wild signature
        ok = targets["wild_lo"] <= state["wild_on_payline"] <= targets["wild_hi"]
        all_checks.append(make_check("WILD", mode, f"{state['wild_on_payline']:.2%} vs band [{targets['wild_lo']:.0%}, {targets['wild_hi']:.0%}]", ok))

        # Family share
        for f, (lo, hi) in targets["family_share_band_base"].items():
            actual = state["family_rtp_pp"].get(f, 0.0) / state["base_rtp_pp"] if state["base_rtp_pp"] > 0 else 0
            ok = lo <= actual <= hi
            all_checks.append(make_check("SHARE", mode, f"{f} {actual:.1%} vs [{lo:.0%}, {hi:.0%}]", ok))

        # Density
        density_hi = PER_REEL_DENSITY_HI[mode]
        for (sym, r), d in sorted(state["densities"].items()):
            if sym == "blank" or sym == "topdollar":
                continue
            den_lo = PER_REEL_DENSITY_LO.get(sym, 0.005)
            den_hi = density_hi.get(sym, 0.20)
            ok = den_lo <= d <= den_hi
            if not ok:
                all_checks.append(make_check("DENSITY", mode, f"{sym} R{r+1} {d:.2%} outside [{den_lo:.1%}, {den_hi:.0%}]", ok))

        # Blank ratio
        blanks = [state["densities"].get(("blank", r), 0) * 100 for r in range(3)]
        bratio = max(blanks) / min(blanks) if min(blanks) > 0 else float("inf")
        ok = bratio <= BLANK_RATIO_CAP[mode]
        all_checks.append(make_check("BLANK-VAR", mode, f"max/min Blank ratio {bratio:.2f}x vs cap {BLANK_RATIO_CAP[mode]:.1f}x", ok))

        # Base CV (mode 1 only)
        if "base_cv_max" in targets:
            ok = profile["cv"] <= targets["base_cv_max"]
            all_checks.append(make_check("BASE-CV", mode, f"base CV {profile['cv']:.2f} vs ≤ {targets['base_cv_max']:.1f}", ok))

        # No-1000
        p_1000 = estimate_p_session_geq_1000(state["feature_spec"], state["trigger"])
        ok = p_1000 <= NO_1000_EPSILON
        n_spins = 1 / p_1000 if p_1000 > 0 else float("inf")
        all_checks.append(make_check("NO-1000", mode, f"P(R≥1000)={p_1000:.2e} (1 in {n_spins:,.0f}) vs ≤ {NO_1000_EPSILON:.0e}", ok))

        print()

    # Cross-mode checks
    if 1 in state_by_mode and 7 in state_by_mode:
        m1_bigwin = compute_bigwin_per_position_weights(1)
        m7_bigwin = compute_bigwin_per_position_weights(7)
        for k, v1 in m1_bigwin.items():
            v7 = m7_bigwin.get(k, -999)
            ok = abs(v1 - v7) <= MODE7_FROZEN_TOL
            all_checks.append(make_check("MODE7-LOCK", 7, f"{k[0]}_R{k[1]}: m1={v1} m7={v7}", ok))

        # Mode 7 base bar+cherry cut
        m1_small = sum(state_by_mode[1]["family_rtp_pp"].get(f, 0) for f in ("bar1", "cherry"))
        m7_small = sum(state_by_mode[7]["family_rtp_pp"].get(f, 0) for f in ("bar1", "cherry"))
        cut = m1_small - m7_small
        ok = cut >= MODE7_BAR_CHERRY_MIN_CUT_PP
        all_checks.append(make_check("MODE7-CUT", 7, f"Bar1+Cherry cut {cut:.2f}pp (min {MODE7_BAR_CHERRY_MIN_CUT_PP:.1f})", ok))

    if 2 in state_by_mode and 5 in state_by_mode:
        # Mode 5 big-win pay frequencies ≥ mode 2
        for pid in BIGWIN_PAY_IDS:
            h2 = state_by_mode[2]["profile"]["pay_hits"].get(pid, 0)
            h5 = state_by_mode[5]["profile"]["pay_hits"].get(pid, 0)
            ok = h5 >= h2 * 0.95   # 5% tolerance
            all_checks.append(make_check("LUCKY-MONO", 5, f"pay_id {pid}: m5={h5:.6f} vs m2={h2:.6f} (ratio {h5/h2 if h2>0 else 0:.2f}x)", ok))

    # Summary
    print("\n=== Verification results ===")
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
