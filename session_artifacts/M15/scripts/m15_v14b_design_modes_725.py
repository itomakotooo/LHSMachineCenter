"""M15 v14b modes 7/2/5 design — derived from mode 1 v14 C38_C14_rtp_target_95 (2026-05-12).

Mode 1 just shipped at C38_C14:
  R1: blank 38.50, cherry 4.00, 1bar 20.20, 2bar 16.50, 3bar 10.30,
      high7 7.20, dd 2.90, jp 0.40
  R2: blank 50.30, cherry 3.50, 1bar 16.50, 2bar 13.50, 3bar 7.30,
      high7 5.70, dd 2.80, jp 0.40
  R3: blank 58.97, cherry 2.50, 1bar 13.50, 2bar 11.00, 3bar 5.50,
      high7 4.70, dd 2.40, topdollar 1.13, jp 0.30
  Total RTP 94.26pp (engine), base 42.77pp, feature 51.49pp,
  hit_session 17.34%, R1 blank 38.50%.

This script designs modes 7, 2, 5 from mode 1 + cross-machine philosophy.

Mode 7 (cut, 85% RTP):
  - K-scaling per philosophy §4: blank × F, top-symbol (dd/h7/topdollar)
    weights × K so top marginals UNCHANGED. Result: pay_id 1/2/21 freq
    preserved (MODE7-BIGPAY), trigger preserved (MODE7-TRIGGER), small-pay
    freq cut (MODE7-CUT), RTP/hit drop.
  - feature_params unchanged (byte-equal m1 v9).

Mode 2 (lucky, 300% RTP):
  - Per-family scalar lift on base. Bar/cherry/dd lifted with bar2 boost
    to satisfy LUCKY-MONO (P(bar2_pure) > P(bar1_pure)) per memory note.
  - Feature_params (mode 2 v9) already tilted: y_count [60,30,10] lift,
    x_val mid-cards lift. Feature EV ~60×, trigger ~3.2% → feature ~192pp.
  - Total RTP target ~300pp.

Mode 5 (super-lucky, 500% RTP):
  - Base copied from mode 2 with a modest lift (per user_brief v1.1 §d).
  - Feature_params (mode 5 v9) heavy: y_count [40,35,25], x_val high-card
    bias → feature EV ~123×, feature ~400pp.
  - Total RTP target ~500pp.

Hard constraints (locked):
  H1: Paytable byte-equal (spec.json pays block)
  H2: feature_params byte-equal v9 (per-mode, LOCKED)
  H3: Strip layout unchanged (36 stops per reel)
  H4: Cross-mode invariants encoded in verify.py
      - [MODE7-BIGPAY]: m7/m1 pay_id 1/2/21 freq ratio ∈ [0.85, 1.15]
      - [MODE7-CUT]: m7 small-pay P < m1 small-pay P (pay_id 9,71,8,7,5,3)
      - [MODE7-TRIGGER]: |m7_trig - m1_trig| ≤ 5e-4
      - [LUCKY-MONO]: m2/m5 hit > m1; m5 hit/trigger ≥ m2
      - [CROSS-RTP]: m7 ∈ [83,87], m2 ∈ [290,310], m5 ∈ [480,520]
      - [TOP-JACKPOT-ESC]: m2 pay1 freq ≤ 1.5× m1; m5 pay1 freq ≥ 1.1× m2
  H5: Avoid 1000× bet+ qualitative.
  H6: Jackpot per-reel marginal ≤ 0.6%.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    analytic_profile_from_marginals,
)
from slot_designer.core.devtools.player_experience import symbol_window_probability
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
WEIGHTS_M1 = _M15_DIR / "weights" / "mode_1" / "weights.json"
WEIGHTS_M2 = _M15_DIR / "weights" / "mode_2" / "weights.json"
WEIGHTS_M5 = _M15_DIR / "weights" / "mode_5" / "weights.json"
WEIGHTS_M7 = _M15_DIR / "weights" / "mode_7" / "weights.json"

engine, _spec = load_engine(SPEC_PATH, WEIGHTS_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator
STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

# Feature_params per mode (LOCKED, byte-equal v9). Load from prod weights files.
FP_BY_MODE = {
    1: json.loads(WEIGHTS_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(WEIGHTS_M2.read_text(encoding="utf-8"))["feature_params"],
    5: json.loads(WEIGHTS_M5.read_text(encoding="utf-8"))["feature_params"],
    7: json.loads(WEIGHTS_M7.read_text(encoding="utf-8"))["feature_params"],
}


def feature_ev_per_trigger(fp):
    """Compute feature E[R] under 4-round accept/reroll flow."""
    dist = _round_payout_distribution(
        tuple(fp["x_count_weights"]),
        tuple(fp["y_count_weights"]),
        tuple(fp["x_value_weights"]),
        tuple(fp["y_value_weights"]),
    )
    accept_thr = fp["accept_threshold"]
    p_accept = sum(p for r, p in dist if r >= accept_thr)
    if p_accept == 0:
        return 0.0, dist
    A = sum(r * p for r, p in dist if r >= accept_thr) / p_accept
    U = sum(r * p for r, p in dist)
    max_r = fp["max_rounds"]
    # E[final] = sum_{i=1..max-1} (1-p)^(i-1) * p * A + (1-p)^(max-1) * U
    reject_streak = 1.0 - p_accept
    ev = 0.0
    for round_idx in range(1, max_r):
        ev += (reject_streak ** (round_idx - 1)) * p_accept * A
    ev += (reject_streak ** (max_r - 1)) * U
    return ev, dist


def feature_p_r_ge(dist, threshold):
    """Probability that the final accepted/forced R is >= threshold."""
    # For per-spin P(R>=X), we approximate as trigger_rate * P_per_trigger
    # where P_per_trigger uses the final distribution. Use a simple bound:
    # P_per_trigger ≈ P(R>=X | single round) * (1 - (1-p_accept)^max_r-1)
    # Actually use the per-trigger formula consistent with verify.py: just
    # sum_{r >= X} p (per-round dist). This matches the verify approximation.
    return sum(p for r, p in dist if r >= threshold)


FEAT_BY_MODE = {}
for mode, fp in FP_BY_MODE.items():
    ev, dist = feature_ev_per_trigger(fp)
    p_r_ge_200 = feature_p_r_ge(dist, 200)
    p_r_ge_1000 = feature_p_r_ge(dist, 1000)
    FEAT_BY_MODE[mode] = {
        "ev": ev,
        "dist": dist,
        "p_r_ge_200": p_r_ge_200,
        "p_r_ge_1000": p_r_ge_1000,
    }


PAY_FAM_MAP = {
    "9":  "cherry1",
    "71": "cherry2",
    "4":  "cherry3",
    "1":  "wild_pure",
    "2":  "high7_wild",
    "21": "high7_pure",
    "3":  "bar3",
    "5":  "bar2",
    "7":  "bar1",
    "8":  "bar_mixed",
}

# Mode 1 v14 C38_C14 marginals — these are the shipped baseline (engine-realized
# slightly different from analytic-target; see design_v14.md §2 — the 0.49pp
# delta is in the topdollar marginal rounding under integer weights).
M1_MARGINALS = [
    # R1
    {"blank": 0.38500, "cherry": 0.04000, "1bar": 0.20200, "2bar": 0.16500,
     "3bar": 0.10300, "high7": 0.07200, "doublediamond": 0.02900,
     "jackpot": 0.00400},
    # R2
    {"blank": 0.50300, "cherry": 0.03500, "1bar": 0.16500, "2bar": 0.13500,
     "3bar": 0.07300, "high7": 0.05700, "doublediamond": 0.02800,
     "jackpot": 0.00400},
    # R3
    {"blank": 0.58970, "cherry": 0.02500, "1bar": 0.13500, "2bar": 0.11000,
     "3bar": 0.05500, "high7": 0.04700, "doublediamond": 0.02400,
     "topdollar": 0.01130, "jackpot": 0.00300},
]


def normalize_marg(m):
    """Recompute blank as residual; ensure sum = 1.0."""
    out = dict(m)
    non_blank = sum(v for k, v in out.items() if k != "blank")
    out["blank"] = max(0.0, 1.0 - non_blank)
    return out


def margs_with_blank(R1_nb, R2_nb, R3_nb, *, with_topdollar_R3=True,
                     topdollar=0.01130, jackpot=(0.00400, 0.00400, 0.00300)):
    """Build 3-reel marginals from per-symbol non-blank fractions.
    R*_nb is a dict like {"cherry": x, "1bar": y, ...} (no blank, no topdollar, no jp).
    """
    R1 = dict(R1_nb)
    R1["jackpot"] = jackpot[0]
    R1 = normalize_marg(R1)

    R2 = dict(R2_nb)
    R2["jackpot"] = jackpot[1]
    R2 = normalize_marg(R2)

    R3 = dict(R3_nb)
    R3["jackpot"] = jackpot[2]
    if with_topdollar_R3:
        R3["topdollar"] = topdollar
    R3 = normalize_marg(R3)

    return [R1, R2, R3]


def evaluate(margs, mode):
    """Evaluate analytic base profile + feature contribution for a given mode."""
    prof = analytic_profile_from_marginals(EV, margs)
    base_rtp_pct = prof["rtp_pct"]
    base_hit = prof["hit_rate"]
    trigger = margs[2].get("topdollar", 0.0)
    feat = FEAT_BY_MODE[mode]
    feature_rtp_pct = trigger * feat["ev"] * 100.0
    total_rtp_pct = base_rtp_pct + feature_rtp_pct
    hit_session = base_hit + trigger
    p_r_ge_1000_per_spin = trigger * feat["p_r_ge_1000"]
    p_r_ge_200_per_spin = trigger * feat["p_r_ge_200"]

    family_pp = defaultdict(float)
    for pid, rtp in prof["pay_rtp"].items():
        fam = PAY_FAM_MAP.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp * 100.0
    high7_combined = family_pp.get("high7_wild", 0.0) + family_pp.get("high7_pure", 0.0)

    family_shares = {}
    if base_rtp_pct > 0:
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "wild_pure"):
            family_shares[fam] = family_pp.get(fam, 0.0) / base_rtp_pct * 100.0
        family_shares["high7"] = high7_combined / base_rtp_pct * 100.0

    p_wild = prof["pay_hits"].get("1", 0.0)
    wild_cadence = 1.0 / p_wild if p_wild > 0 else float("inf")
    return {
        "mode": mode,
        "total_rtp_pct": total_rtp_pct,
        "base_rtp_pct": base_rtp_pct,
        "feature_rtp_pct": feature_rtp_pct,
        "hit_session": hit_session * 100,
        "base_hit_pct": base_hit * 100,
        "trigger_pct": trigger * 100,
        "trigger": trigger,
        "r1_blank_pct": margs[0].get("blank", 0) * 100,
        "r2_blank_pct": margs[1].get("blank", 0) * 100,
        "r3_blank_pct": margs[2].get("blank", 0) * 100,
        "pay_hits": prof["pay_hits"],
        "pay_rtp": prof["pay_rtp"],
        "family_pp": dict(family_pp),
        "high7_combined_pp": high7_combined,
        "family_shares": family_shares,
        "wild_cadence": wild_cadence,
        "cv": prof["cv"],
        "p_r_ge_1000_per_spin": p_r_ge_1000_per_spin,
        "p_r_ge_200_per_spin": p_r_ge_200_per_spin,
        "margs": margs,
    }


# Compute mode 1 baseline once
M1_RESULT = evaluate(M1_MARGINALS, 1)


# ----------------------------------------------------------------------------
# Mode 7 designs (cut mode, 85% RTP)
# Approach: K-scaling. Cut blank by F, scale topdollar/dd/high7 by K_r per reel
# such that their marginals stay UNCHANGED. Small-pay marginals drop proportionally.
# ----------------------------------------------------------------------------

def m7_k_scale(F):
    """K-scaling derivation:
    Suppose reel r has, in mode 1 marginals: blank=B, top=T (h7+dd+topdollar+jp),
    other=O (=1-B-T). Other-pay symbols include cherry, 1bar, 2bar, 3bar.

    Let w_blank be the per-stop weight of blank symbols. Multiply w_blank × F.
    Then new total weight = (B*total*F + ...) — non-trivial because non-blank
    weights are different per stop.

    Marginal-level formulation (since we have marginals directly):
    - We want top-symbol marginals unchanged: T' = T
    - We want blank marginal lifted: B' > B (this is the cut mechanism)
    - Other-pay marginals scale: O' = 1 - B' - T

    If we define K such that:
      O' = O × (1 / K_o)  where K_o = (1-B-T) / (1-B'-T)

    Strict per philosophy §4: small_pay_cut requires O' < O strictly. So we
    need 1 - B' - T < 1 - B - T → B' > B → indeed blank lifted.

    For trigger preservation: topdollar marginal R3 unchanged → trigger preserved.
    For big-pay preservation: dd, h7 marginals unchanged → pay_id 1, 2, 21 freq
    preserved (modulo combinatorial cross-reel effects).

    Strategy: lift blank by adding F*B_extra; recompute other-pay marginals by
    proportional shrink.
    """
    new_margs = []
    for r_idx, m1_m in enumerate(M1_MARGINALS):
        B = m1_m.get("blank", 0)
        top_syms = ("doublediamond", "high7", "topdollar", "jackpot")
        T = sum(m1_m.get(s, 0) for s in top_syms)
        O = 1.0 - B - T
        # Lift blank: B' = min(B * F, 1 - T - eps)
        new_B = min(B * F, 1.0 - T - 0.005)
        new_O = 1.0 - new_B - T
        scale = new_O / O if O > 0 else 1.0
        nm = {}
        for sym, mg in m1_m.items():
            if sym == "blank":
                nm[sym] = new_B
            elif sym in top_syms:
                nm[sym] = mg  # unchanged
            else:
                nm[sym] = mg * scale
        new_margs.append(nm)
    return new_margs


def M7_F100():
    """F=1.00 baseline check (mode 7 = mode 1 — should be identical)."""
    return m7_k_scale(1.00)


def M7_F105():
    return m7_k_scale(1.05)


def M7_F108():
    return m7_k_scale(1.08)


def M7_F110():
    """Targeting 85% RTP. Mode 1 base 42.77pp; mode 7 needs base ~33pp.
    Other-pay scale O'/O = 33/42.77 = 0.77. From m7_k_scale: B' = F·B.
    Per R3: B=0.5897, T=0.0843, O=0.326. O' = 1 - F·B - T = 0.326 - F·B + B
           Therefore F=1+0.077/B for that 0.077/0.5897=13.05% B lift on R3.
    Try F=1.10 (~10% blank lift) as the right magnitude."""
    return m7_k_scale(1.10)


def M7_F112():
    return m7_k_scale(1.12)


def M7_F115():
    return m7_k_scale(1.15)


def M7_F118():
    return m7_k_scale(1.18)


def M7_F120():
    return m7_k_scale(1.20)


def M7_F125():
    return m7_k_scale(1.25)


# ----------------------------------------------------------------------------
# Mode 2 designs (lucky, 300% RTP) — independent archetype lift
#
# Per philosophy §C cross-mode: mode 2 hit rate 1.5-2× mode 1, all-tier lift.
# M15 spec: mode 2 hit band [0.30, 0.35] (verify.py), RTP band [290, 310].
#
# Constraint per memory project_slot_designer §I LUCKY-MONO: P(bar2_pure) >
# P(bar1_pure) and P(bar2_pure) > P(bar3_pure). This is because lucky mode
# has dd density up, and bar2 line_3_same becomes more probable via wild
# substitution path.
#
# Actually that interpretation requires reading verify.py — let me check.
# Looking at verify.py line 645-648: lucky modes carve-out for HIERARCHY_PAIRS_BAR.
# The carve-out is INFO (line 654 _info), NOT enforced as RED. Lucky modes
# are allowed to violate inverse pyramid for bar (bar2 can be > bar1 etc.).
#
# Strategy:
#   1. Bump dd density (lucky wild presence) — drives feature density and
#      enables wild-boost bar paths to higher mults.
#   2. Lift cherry slightly, lift bar2 most aggressively (lucky-mono signature).
#   3. Trigger rate must be > m1 trigger (~1.13% → ~3.2% for [LUCKY-MONO]).
#      Per existing m2 v8: trigger ~3.2%. We can replicate by lifting
#      topdollar marginal on R3.
# ----------------------------------------------------------------------------

def m2_per_reel_lift(cherry_R1, cherry_R2, cherry_R3,
                    bar1_R1, bar1_R2, bar1_R3,
                    bar2_R1, bar2_R2, bar2_R3,
                    bar3_R1, bar3_R2, bar3_R3,
                    h7_R1, h7_R2, h7_R3,
                    dd_R1, dd_R2, dd_R3,
                    td_R3):
    R1 = {"cherry": cherry_R1, "1bar": bar1_R1, "2bar": bar2_R1, "3bar": bar3_R1,
          "high7": h7_R1, "doublediamond": dd_R1}
    R2 = {"cherry": cherry_R2, "1bar": bar1_R2, "2bar": bar2_R2, "3bar": bar3_R2,
          "high7": h7_R2, "doublediamond": dd_R2}
    R3 = {"cherry": cherry_R3, "1bar": bar1_R3, "2bar": bar2_R3, "3bar": bar3_R3,
          "high7": h7_R3, "doublediamond": dd_R3}
    return margs_with_blank(R1, R2, R3, topdollar=td_R3)


def M2_A_central_lucky():
    """M2-A: trigger ~3.0% (feature ~180pp), base target ~110pp = ~290pp total.
    Bar hierarchy: 2bar > 1bar > 3bar at MARGINAL level (per shipped m2 pattern
    to achieve LUCKY-MONO bar2 peak via wild-substitution boost on bar2 line).
    dd kept close to m1 to satisfy TOP-JACKPOT-ESC m2/m1 cap 1.5×.
    cherry 7 / 6 / 5, 1bar 15 / 14 / 13, 2bar 22 / 19 / 16, 3bar 13 / 9 / 7,
    h7 10 / 9 / 7, dd 3.2 / 3.0 / 2.6. td R3 3.0."""
    return m2_per_reel_lift(
        0.070, 0.060, 0.050,
        0.150, 0.140, 0.130,
        0.220, 0.190, 0.160,    # 2bar > 1bar > 3bar (lucky carve-out)
        0.130, 0.090, 0.070,
        0.100, 0.090, 0.070,
        0.032, 0.030, 0.026,    # dd close to m1 (cadence cap)
        0.030,
    )


def M2_B_higher_h7_central():
    """M2-B: h7 lifted more, bar2 strong, dd close to m1.
    cherry 6 / 5 / 4, 1bar 14 / 13 / 12, 2bar 22 / 19 / 16, 3bar 13 / 9 / 7,
    h7 13 / 11 / 9, dd 3.2 / 3.0 / 2.6. td R3 3.0."""
    return m2_per_reel_lift(
        0.060, 0.050, 0.040,
        0.140, 0.130, 0.120,
        0.220, 0.190, 0.160,
        0.130, 0.090, 0.070,
        0.130, 0.110, 0.090,
        0.032, 0.030, 0.026,
        0.030,
    )


def M2_C_classic_lucky():
    """M2-C: balanced lift mirroring shipped m2 marginal pattern with dd safe.
    cherry 7 / 7 / 6, 1bar 13 / 14 / 13, 2bar 21 / 19 / 18, 3bar 14 / 9 / 12,
    h7 10 / 11 / 11, dd 3.0 / 3.0 / 2.5. td R3 3.0."""
    return m2_per_reel_lift(
        0.070, 0.070, 0.060,
        0.130, 0.140, 0.130,
        0.210, 0.190, 0.180,
        0.140, 0.090, 0.120,
        0.100, 0.110, 0.110,
        0.030, 0.030, 0.025,
        0.030,
    )


def M2_D_higher_h7():
    """M2-D: h7 lifted, bar2 strong. Base target ~110pp. dd safe.
    cherry 7 / 6 / 4, 1bar 13 / 14 / 12, 2bar 22 / 18 / 14, 3bar 12 / 8 / 6,
    h7 14 / 13 / 11, dd 3.0 / 3.0 / 2.6. td R3 3.0."""
    return m2_per_reel_lift(
        0.070, 0.060, 0.040,
        0.130, 0.140, 0.120,
        0.220, 0.180, 0.140,
        0.120, 0.080, 0.060,
        0.140, 0.130, 0.110,
        0.030, 0.030, 0.026,
        0.030,
    )


def M2_E_higher_RTP():
    """M2-E: target ~305pp upper edge. bar2 strong, cherry lift, td 3.2.
    dd safe. cherry 8 / 7 / 5, 1bar 14 / 14 / 12, 2bar 24 / 20 / 16,
    3bar 14 / 9 / 7, h7 11 / 9 / 7, dd 3.2 / 3.0 / 2.6. td R3 3.2."""
    return m2_per_reel_lift(
        0.080, 0.070, 0.050,
        0.140, 0.140, 0.120,
        0.240, 0.200, 0.160,
        0.140, 0.090, 0.070,
        0.110, 0.090, 0.070,
        0.032, 0.030, 0.026,
        0.032,
    )


def M2_F_high_cherry():
    """M2-F: cherry-heavy lucky (cherry 9/8/6) → drives hit toward 32-35%.
    cherry 9 / 8 / 6, 1bar 13 / 13 / 11, 2bar 22 / 18 / 14, 3bar 13 / 9 / 7,
    h7 10 / 8 / 7, dd 3.0 / 3.0 / 2.5. td R3 3.0."""
    return m2_per_reel_lift(
        0.090, 0.080, 0.060,
        0.130, 0.130, 0.110,
        0.220, 0.180, 0.140,
        0.130, 0.090, 0.070,
        0.100, 0.080, 0.070,
        0.030, 0.030, 0.025,
        0.030,
    )


def M2_G_central_high_cherry():
    """M2-G: cherry boosted further (10/8/6) + bar2 strong. Hit target ~33%.
    cherry 10 / 8 / 6, 1bar 13 / 13 / 11, 2bar 22 / 18 / 14, 3bar 13 / 9 / 7,
    h7 11 / 9 / 7, dd 3.2 / 3.0 / 2.6. td R3 3.0."""
    return m2_per_reel_lift(
        0.100, 0.080, 0.060,
        0.130, 0.130, 0.110,
        0.220, 0.180, 0.140,
        0.130, 0.090, 0.070,
        0.110, 0.090, 0.070,
        0.032, 0.030, 0.026,
        0.030,
    )


def M2_H_aggressive_bars_cherry():
    """M2-H: full lift, cherry 10/9/7, bars heavy, h7 14/12/10, dd 3.2/3.0/2.6.
    Target ~300pp / hit ~33%."""
    return m2_per_reel_lift(
        0.100, 0.090, 0.070,
        0.150, 0.150, 0.130,
        0.250, 0.220, 0.180,
        0.140, 0.090, 0.070,
        0.140, 0.120, 0.100,
        0.032, 0.030, 0.026,
        0.030,
    )


def M2_I_h7_anchor():
    """M2-I: h7 heavy-anchor lucky. cherry 8/7/5, 1bar 14/14/12, 2bar 23/19/15,
    3bar 13/9/7, h7 16/14/12, dd 3.2/3.0/2.6. td 3.0."""
    return m2_per_reel_lift(
        0.080, 0.070, 0.050,
        0.140, 0.140, 0.120,
        0.230, 0.190, 0.150,
        0.130, 0.090, 0.070,
        0.160, 0.140, 0.120,
        0.032, 0.030, 0.026,
        0.030,
    )


def M2_J_balanced_high():
    """M2-J: balanced higher overall. cherry 9/8/6, 1bar 14/14/12,
    2bar 24/21/17, 3bar 14/10/8, h7 13/11/9, dd 3.2/3.0/2.6. td 3.0."""
    return m2_per_reel_lift(
        0.090, 0.080, 0.060,
        0.140, 0.140, 0.120,
        0.240, 0.210, 0.170,
        0.140, 0.100, 0.080,
        0.130, 0.110, 0.090,
        0.032, 0.030, 0.026,
        0.030,
    )


def M2_K_balanced_high_v2():
    """M2-K: variant of J with 2bar+3bar boost. cherry 8/7/5,
    1bar 14/14/12, 2bar 24/22/18, 3bar 16/12/10, h7 12/10/8, dd 3.2/3.0/2.6.
    td 3.0."""
    return m2_per_reel_lift(
        0.080, 0.070, 0.050,
        0.140, 0.140, 0.120,
        0.240, 0.220, 0.180,
        0.160, 0.120, 0.100,
        0.120, 0.100, 0.080,
        0.032, 0.030, 0.026,
        0.030,
    )


def M2_L_uneven_dd():
    """M2-L: dd asymmetric per shipped m2 pattern (high R1/R2, low R3 to
    keep cadence safe while maximizing wild-substitution boost on R1/R2
    line pays). cherry 8/7/5, 1bar 14/14/12, 2bar 23/20/16, 3bar 15/10/8,
    h7 12/10/8, dd 4.5/4.5/1.5 → product 3.04e-5 = 1/33k (just inside 1.5x m1).
    td 3.0."""
    return m2_per_reel_lift(
        0.080, 0.070, 0.050,
        0.140, 0.140, 0.120,
        0.230, 0.200, 0.160,
        0.150, 0.100, 0.080,
        0.120, 0.100, 0.080,
        0.045, 0.045, 0.015,    # uneven dd: high R1/R2 boost, low R3 safety
        0.030,
    )


def M2_M_uneven_dd_high_cherry():
    """M2-M: M2-L with cherry boosted. cherry 10/8/6."""
    return m2_per_reel_lift(
        0.100, 0.080, 0.060,
        0.140, 0.140, 0.120,
        0.230, 0.200, 0.160,
        0.150, 0.100, 0.080,
        0.120, 0.100, 0.080,
        0.045, 0.045, 0.015,
        0.030,
    )


def M2_N_uneven_dd_strong_h7():
    """M2-N: uneven dd + h7 lifted (seven-anchor lucky).
    cherry 8/7/5, 1bar 14/14/12, 2bar 22/19/15, 3bar 14/10/8, h7 14/12/10,
    dd 4.5/4.5/1.5. td 3.0."""
    return m2_per_reel_lift(
        0.080, 0.070, 0.050,
        0.140, 0.140, 0.120,
        0.220, 0.190, 0.150,
        0.140, 0.100, 0.080,
        0.140, 0.120, 0.100,
        0.045, 0.045, 0.015,
        0.030,
    )


def M2_O_aggressive_uneven():
    """M2-O: aggressive variant of L: cherry 9/8/6, h7 13/11/9, dd 5/5/1.5."""
    return m2_per_reel_lift(
        0.090, 0.080, 0.060,
        0.140, 0.140, 0.120,
        0.230, 0.200, 0.160,
        0.150, 0.100, 0.080,
        0.130, 0.110, 0.090,
        0.050, 0.050, 0.015,
        0.030,
    )


def M2_P_max_uneven_dd():
    """M2-P: max dd R1/R2 to lift base RTP, dd R3 minimal. Cherry 10/9/7.
    dd 5.5/5.0/1.0 → product 2.75e-5 = 1/36k (within 1.5x m1).
    1bar 14/14/12, 2bar 25/22/18, 3bar 16/11/9, h7 13/11/9. td 3.0."""
    return m2_per_reel_lift(
        0.100, 0.090, 0.070,
        0.140, 0.140, 0.120,
        0.250, 0.220, 0.180,
        0.160, 0.110, 0.090,
        0.130, 0.110, 0.090,
        0.055, 0.050, 0.010,
        0.030,
    )


def M2_Q_h7_max_uneven_dd():
    """M2-Q: h7 anchored + max uneven dd. cherry 9/8/6, 1bar 14/14/12,
    2bar 25/22/18, 3bar 15/10/8, h7 15/13/11, dd 5.5/5.0/1.0. td 3.0."""
    return m2_per_reel_lift(
        0.090, 0.080, 0.060,
        0.140, 0.140, 0.120,
        0.250, 0.220, 0.180,
        0.150, 0.100, 0.080,
        0.150, 0.130, 0.110,
        0.055, 0.050, 0.010,
        0.030,
    )


def M2_R_balanced_max():
    """M2-R: balanced + max uneven dd. cherry 10/9/7, 1bar 15/15/13,
    2bar 24/21/17, 3bar 14/10/8, h7 13/11/9, dd 5.5/5.0/1.0. td 3.0."""
    return m2_per_reel_lift(
        0.100, 0.090, 0.070,
        0.150, 0.150, 0.130,
        0.240, 0.210, 0.170,
        0.140, 0.100, 0.080,
        0.130, 0.110, 0.090,
        0.055, 0.050, 0.010,
        0.030,
    )


def M2_S_target_300():
    """M2-S: target 300 exactly. dd 4.8/4.8/1.0 → cube 2.30e-5 = 1/43k.
    cherry 9/8/6, 1bar 14/14/12, 2bar 25/22/17, 3bar 15/11/9, h7 13/11/9.
    td 3.0."""
    return m2_per_reel_lift(
        0.090, 0.080, 0.060,
        0.140, 0.140, 0.120,
        0.250, 0.220, 0.170,
        0.150, 0.110, 0.090,
        0.130, 0.110, 0.090,
        0.048, 0.048, 0.010,
        0.030,
    )


# ----------------------------------------------------------------------------
# Mode 5 designs (super-lucky, 500% RTP).
# Per philosophy §C: mode 5 = mode 2 with base lift in top + heavy feature.
# Per user_brief v1.1 §d: m5 base may be lifted modestly over m2 (not byte-equal).
# Per [TOP-JACKPOT-ESC]: m5 pay_id 1 cadence ≥ 1.1× m2 → dd density must be ≥ m2.
# Per [LUCKY-MONO]: m5 hit ≥ m2 hit; m5 trigger ≥ m2 trigger.
#
# Approach: take winning M2 candidate and modestly lift dd density + top
# symbols. Total RTP target 480-520 via feature_params m5 (~123× EV, ~3.2%
# trigger → feature ~400pp + base ~100pp).
# ----------------------------------------------------------------------------

def m5_from_m2(m2_marg, *, dd_lift_pct=10.0, td_lift_pct=2.0, cherry_lift_pct=5.0):
    """Take m2 marginals and apply small lifts to dd + top symbols + cherry.
    dd_lift_pct = 10 means dd density up 10% relative.
    td_lift_pct = 2 means topdollar marginal R3 up 2% (relative).
    cherry_lift_pct = 5 means cherry up 5% (relative).
    """
    new_margs = []
    for r_idx, m in enumerate(m2_marg):
        nm = dict(m)
        if "doublediamond" in nm:
            nm["doublediamond"] *= (1.0 + dd_lift_pct / 100.0)
        if "cherry" in nm:
            nm["cherry"] *= (1.0 + cherry_lift_pct / 100.0)
        if r_idx == 2 and "topdollar" in nm:
            nm["topdollar"] *= (1.0 + td_lift_pct / 100.0)
        new_margs.append(normalize_marg(nm))
    return new_margs


def M5_A_classic_from_M2_E():
    """M5-A: from M2_E with modest lifts. dd+8%, td+3%, cherry+3%."""
    return m5_from_m2(M2_E_higher_RTP(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


def M5_B_modest_lift_from_M2_G():
    """M5-B: from M2_G (cherry-heavy) with dd+8%, td+3%, cherry+3%."""
    return m5_from_m2(M2_G_central_high_cherry(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


def M5_C_from_M2_L():
    """M5-C: from M2_L (uneven dd). dd+8% on R1/R2 (R3 stays 1.5), td+3%, cherry+3%."""
    return m5_from_m2(M2_L_uneven_dd(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


def M5_D_from_M2_O():
    """M5-D: from M2_O with dd+5%, td+3%, cherry+3% (M2_O already aggressive)."""
    return m5_from_m2(M2_O_aggressive_uneven(), dd_lift_pct=5, td_lift_pct=3, cherry_lift_pct=3)


def M5_E_modest_from_M2_O():
    """M5-E: minimal lift from M2_O. dd+2%, td+1%, cherry+1%."""
    return m5_from_m2(M2_O_aggressive_uneven(), dd_lift_pct=2, td_lift_pct=1, cherry_lift_pct=1)


def M5_F_from_M2_N():
    """M5-F: from M2_N (h7-heavy + uneven dd). dd+8%, td+3%, cherry+3%."""
    return m5_from_m2(M2_N_uneven_dd_strong_h7(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


def M5_G_from_M2_M():
    """M5-G: from M2_M (uneven dd + high cherry)."""
    return m5_from_m2(M2_M_uneven_dd_high_cherry(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


def M5_H_from_M2_Q():
    """M5-H: from M2_Q (winning m2 candidate). dd+8%, td+3%, cherry+3%."""
    return m5_from_m2(M2_Q_h7_max_uneven_dd(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


def M5_I_modest_from_M2_Q():
    """M5-I: minimal lift from M2_Q. dd+3%, td+1%, cherry+1%."""
    return m5_from_m2(M2_Q_h7_max_uneven_dd(), dd_lift_pct=3, td_lift_pct=1, cherry_lift_pct=1)


def M5_J_aggressive_from_M2_Q():
    """M5-J: aggressive lift. dd+15%, td+5%, cherry+5%."""
    return m5_from_m2(M2_Q_h7_max_uneven_dd(), dd_lift_pct=15, td_lift_pct=5, cherry_lift_pct=5)


def M5_K_from_M2_S():
    """M5-K: from M2_S. dd+8%, td+3%, cherry+3%."""
    return m5_from_m2(M2_S_target_300(), dd_lift_pct=8, td_lift_pct=3, cherry_lift_pct=3)


# ============================================================================
# Cross-mode invariant checks
# ============================================================================

def check_mode7(m7, m1):
    """Returns dict of {check_name: (status, value, expected)}."""
    out = {}

    # MODE7-CUT: m7 small-pay P < m1 small-pay P (pay_id 9,71,8,7,5,3)
    small_pids = ["9", "71", "8", "7", "5", "3"]
    for pid in small_pids:
        m1_p = m1["pay_hits"].get(pid, 0.0)
        m7_p = m7["pay_hits"].get(pid, 0.0)
        ok = m7_p < m1_p - 1e-9
        out[f"MODE7-CUT pay{pid}"] = ("PASS" if ok else "FAIL",
                                      f"m7={m7_p*100:.4f}% m1={m1_p*100:.4f}%",
                                      "m7<m1")

    # MODE7-BIGPAY: m7/m1 pay_id 1/2/21 ratio ∈ [0.85, 1.15]
    big_pids = ["1", "2", "21"]
    for pid in big_pids:
        m1_p = m1["pay_hits"].get(pid, 0.0)
        m7_p = m7["pay_hits"].get(pid, 0.0)
        ratio = m7_p / m1_p if m1_p > 0 else float("inf")
        ok = 0.85 <= ratio <= 1.15
        out[f"MODE7-BIGPAY pay{pid}"] = ("PASS" if ok else "FAIL",
                                          f"ratio={ratio:.3f}",
                                          "[0.85, 1.15]")

    # MODE7-TRIGGER: |m7_trig - m1_trig| ≤ 5e-4
    diff = abs(m7["trigger"] - m1["trigger"])
    ok = diff <= 5e-4
    out["MODE7-TRIGGER"] = ("PASS" if ok else "FAIL",
                             f"diff={diff:.6f}", "≤ 5e-4")

    # CROSS-RTP m7: RTP in [83, 87], RTP < m1
    rtp_ok = 83.0 <= m7["total_rtp_pct"] <= 87.0
    out["CROSS-RTP m7 band"] = ("PASS" if rtp_ok else "FAIL",
                                  f"{m7['total_rtp_pct']:.3f}pp", "[83, 87]")
    ladder_ok = m7["total_rtp_pct"] < m1["total_rtp_pct"]
    out["CROSS-RTP m7<m1"] = ("PASS" if ladder_ok else "FAIL",
                              f"m7={m7['total_rtp_pct']:.2f} m1={m1['total_rtp_pct']:.2f}",
                              "m7 < m1")

    # HIT band m7 [10, 16] (base hit)
    hit_ok = 10.0 <= m7["base_hit_pct"] <= 16.0
    out["HIT m7 band"] = ("PASS" if hit_ok else "FAIL",
                          f"{m7['base_hit_pct']:.3f}%", "[10, 16]")

    # LUCKY-MONO m7 < m1 hit
    hit_ladder_ok = m7["base_hit_pct"] < m1["base_hit_pct"]
    out["LUCKY-MONO m7<m1 hit"] = ("PASS" if hit_ladder_ok else "FAIL",
                                    f"m7={m7['base_hit_pct']:.2f}% m1={m1['base_hit_pct']:.2f}%",
                                    "m7 < m1")

    # P(R>=1000/spin) cap
    p1k_ok = m7["p_r_ge_1000_per_spin"] <= 1e-5
    out["1000+ m7"] = ("PASS" if p1k_ok else "FAIL",
                       f"{m7['p_r_ge_1000_per_spin']:.3e}", "≤ 1e-5")

    return out


def check_mode2(m2, m1):
    out = {}

    # CROSS-RTP m2 band [290, 310], m2 > m1
    rtp_ok = 290.0 <= m2["total_rtp_pct"] <= 310.0
    out["CROSS-RTP m2 band"] = ("PASS" if rtp_ok else "FAIL",
                                  f"{m2['total_rtp_pct']:.3f}pp", "[290, 310]")
    ladder_ok = m2["total_rtp_pct"] > m1["total_rtp_pct"]
    out["CROSS-RTP m2>m1"] = ("PASS" if ladder_ok else "FAIL",
                               f"m2={m2['total_rtp_pct']:.2f}", ">m1")

    # HIT m2 band [30, 35]
    hit_ok = 30.0 <= m2["base_hit_pct"] <= 35.0
    out["HIT m2 band"] = ("PASS" if hit_ok else "FAIL",
                          f"{m2['base_hit_pct']:.3f}%", "[30, 35]")

    # LUCKY-MONO m2 hit > m1
    hit_mono_ok = m2["base_hit_pct"] > m1["base_hit_pct"]
    out["LUCKY-MONO m2>m1 hit"] = ("PASS" if hit_mono_ok else "FAIL",
                                    f"m2={m2['base_hit_pct']:.2f} m1={m1['base_hit_pct']:.2f}",
                                    "m2 > m1")

    # LUCKY-MONO m2 trigger ≥ m1
    trig_mono_ok = m2["trigger"] >= m1["trigger"] - 1e-9
    out["LUCKY-MONO m2>=m1 trig"] = ("PASS" if trig_mono_ok else "FAIL",
                                       f"m2={m2['trigger_pct']:.3f}% m1={m1['trigger_pct']:.3f}%",
                                       "m2 ≥ m1")

    # LUCKY-MONO P(bar2) > P(bar1) AND P(bar2) > P(bar3)
    p_b1 = m2["pay_hits"].get("7", 0.0)   # bar1_pure pay
    p_b2 = m2["pay_hits"].get("5", 0.0)   # bar2_pure
    p_b3 = m2["pay_hits"].get("3", 0.0)   # bar3_pure
    bar_mono = p_b2 > p_b1 and p_b2 > p_b3
    out["LUCKY-MONO bar2 peak"] = ("PASS" if bar_mono else "FAIL",
                                     f"b1={p_b1*100:.4f}% b2={p_b2*100:.4f}% b3={p_b3*100:.4f}%",
                                     "b2>b1 & b2>b3")

    # TOP-JACKPOT-ESC m2/m1 pay1 cadence ≤ 1.5×
    m1_p1 = m1["pay_hits"].get("1", 0.0)
    m2_p1 = m2["pay_hits"].get("1", 0.0)
    ratio = m2_p1 / m1_p1 if m1_p1 > 0 else float("inf")
    ok = ratio <= 1.5
    out["TOP-JACKPOT-ESC m2/m1"] = ("PASS" if ok else "FAIL",
                                      f"ratio={ratio:.3f}", "≤ 1.5")

    # 1000+ m2
    p1k_ok = m2["p_r_ge_1000_per_spin"] <= 1e-5
    out["1000+ m2"] = ("PASS" if p1k_ok else "FAIL",
                       f"{m2['p_r_ge_1000_per_spin']:.3e}", "≤ 1e-5")

    return out


def check_mode5(m5, m2, m1):
    out = {}

    # CROSS-RTP m5 band [480, 520], m5 > m2
    rtp_ok = 480.0 <= m5["total_rtp_pct"] <= 520.0
    out["CROSS-RTP m5 band"] = ("PASS" if rtp_ok else "FAIL",
                                  f"{m5['total_rtp_pct']:.3f}pp", "[480, 520]")
    ladder_ok = m5["total_rtp_pct"] > m2["total_rtp_pct"]
    out["CROSS-RTP m5>m2"] = ("PASS" if ladder_ok else "FAIL",
                               f"m5={m5['total_rtp_pct']:.2f}", ">m2")

    # HIT m5 band [30, 35]
    hit_ok = 30.0 <= m5["base_hit_pct"] <= 35.0
    out["HIT m5 band"] = ("PASS" if hit_ok else "FAIL",
                          f"{m5['base_hit_pct']:.3f}%", "[30, 35]")

    # LUCKY-MONO m5 hit ≥ m2
    hit_mono_ok = m5["base_hit_pct"] >= m2["base_hit_pct"] - 1e-9
    out["LUCKY-MONO m5>=m2 hit"] = ("PASS" if hit_mono_ok else "FAIL",
                                     f"m5={m5['base_hit_pct']:.4f}% m2={m2['base_hit_pct']:.4f}%",
                                     "m5 ≥ m2")

    # LUCKY-MONO m5 trigger ≥ m2
    trig_mono_ok = m5["trigger"] >= m2["trigger"] - 1e-9
    out["LUCKY-MONO m5>=m2 trig"] = ("PASS" if trig_mono_ok else "FAIL",
                                       f"m5={m5['trigger_pct']:.4f}% m2={m2['trigger_pct']:.4f}%",
                                       "m5 ≥ m2")

    # LUCKY-MONO P(bar2) > P(bar1) AND P(bar2) > P(bar3)
    p_b1 = m5["pay_hits"].get("7", 0.0)
    p_b2 = m5["pay_hits"].get("5", 0.0)
    p_b3 = m5["pay_hits"].get("3", 0.0)
    bar_mono = p_b2 > p_b1 and p_b2 > p_b3
    out["LUCKY-MONO bar2 peak"] = ("PASS" if bar_mono else "FAIL",
                                     f"b1={p_b1*100:.4f}% b2={p_b2*100:.4f}% b3={p_b3*100:.4f}%",
                                     "b2>b1 & b2>b3")

    # TOP-JACKPOT-ESC m5/m2 pay1 ≥ 1.1×
    m2_p1 = m2["pay_hits"].get("1", 0.0)
    m5_p1 = m5["pay_hits"].get("1", 0.0)
    ratio = m5_p1 / m2_p1 if m2_p1 > 0 else float("inf")
    ok = ratio >= 1.1
    out["TOP-JACKPOT-ESC m5/m2"] = ("PASS" if ok else "FAIL",
                                      f"ratio={ratio:.3f}", "≥ 1.1")

    # 1000+ m5
    p1k_ok = m5["p_r_ge_1000_per_spin"] <= 1e-5
    out["1000+ m5"] = ("PASS" if p1k_ok else "FAIL",
                       f"{m5['p_r_ge_1000_per_spin']:.3e}", "≤ 1e-5")

    return out


def jackpot_check(r):
    """Returns dict of jackpot-related checks."""
    out = {}
    for i in (0, 1, 2):
        jp = r["margs"][i].get("jackpot", 0.0) * 100
        ok = jp <= 0.6
        out[f"R{i+1} jackpot"] = ("PASS" if ok else "FAIL",
                                  f"{jp:.3f}%", "≤ 0.6%")
    return out


def print_mode_report(name, r, *, checks=None):
    print(f"\n======== {name} ========")
    print(f"  total_rtp={r['total_rtp_pct']:.3f}pp  (base={r['base_rtp_pct']:.2f}pp + feat={r['feature_rtp_pct']:.2f}pp)")
    print(f"  hit_session={r['hit_session']:.3f}%  base_hit={r['base_hit_pct']:.2f}%  trigger={r['trigger_pct']:.3f}%")
    print(f"  R1_blank={r['r1_blank_pct']:.2f}%  R2_blank={r['r2_blank_pct']:.2f}%  R3_blank={r['r3_blank_pct']:.2f}%")
    print(f"  wild_cadence=1/{r['wild_cadence']:.0f}")
    print(f"  base_cv={r['cv']:.3f}")
    print(f"  P(R>=200/spin)={r['p_r_ge_200_per_spin']:.3e}  P(R>=1000/spin)={r['p_r_ge_1000_per_spin']:.3e}")
    fs = r["family_shares"]
    print(f"  family_shares:")
    for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                "bar_mixed", "high7", "wild_pure"):
        v = fs.get(fam, 0)
        print(f"    {fam}: {v:.2f}%")
    print(f"  Per-pay P% (top families):")
    for pid in ("9", "71", "4", "1", "2", "21", "3", "5", "7", "8"):
        p = r["pay_hits"].get(pid, 0.0) * 100
        rtp = r["pay_rtp"].get(pid, 0.0) * 100
        fam = PAY_FAM_MAP.get(pid)
        one_in = 1.0 / (p/100) if p > 0 else float("inf")
        print(f"    pay{pid} ({fam}): P={p:.4f}% (1/{one_in:.0f}) RTP={rtp:.3f}pp")
    if checks is not None:
        print(f"  ----- Cross-mode invariants -----")
        for name, (status, val, expected) in checks.items():
            print(f"    [{status}] {name}: got {val}  expected {expected}")


# ============================================================================
# Full sweep
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("M15 v14b modes 7/2/5 design — derived from mode 1 v14 C38_C14_rtp_target_95")
    print("=" * 80)
    print()

    print("\n#### MODE 1 BASELINE (C38_C14, shipped) ####")
    print_mode_report("Mode 1 (baseline)", M1_RESULT)

    # ============================================================
    # MODE 7
    # ============================================================
    print("\n\n" + "=" * 80)
    print("MODE 7 candidates (cut mode, RTP target 85%)")
    print("=" * 80)

    m7_candidates = [
        ("M7_F100 (verify)", M7_F100()),
        ("M7_F105 (F=1.05)", M7_F105()),
        ("M7_F108 (F=1.08)", M7_F108()),
        ("M7_F110 (F=1.10)", M7_F110()),
        ("M7_F112 (F=1.12)", M7_F112()),
        ("M7_F115 (F=1.15)", M7_F115()),
        ("M7_F118 (F=1.18)", M7_F118()),
        ("M7_F120 (F=1.20)", M7_F120()),
        ("M7_F125 (F=1.25)", M7_F125()),
    ]
    m7_results = []
    for name, margs in m7_candidates:
        r = evaluate(margs, 7)
        checks = check_mode7(r, M1_RESULT)
        jchecks = jackpot_check(r)
        m7_results.append((name, r, checks, jchecks))
        n_fail = sum(1 for s, _, _ in checks.values() if s == "FAIL")
        n_jp_fail = sum(1 for s, _, _ in jchecks.values() if s == "FAIL")
        print(f"\n--- {name}: RTP={r['total_rtp_pct']:.2f}pp hit_base={r['base_hit_pct']:.2f}% "
              f"R1_blank={r['r1_blank_pct']:.2f}% n_fail={n_fail} n_jp_fail={n_jp_fail} ---")

    # Print detailed report for best m7 candidate(s)
    m7_winners = [(n, r, c, jc) for (n, r, c, jc) in m7_results
                  if (sum(1 for s, _, _ in c.values() if s == "FAIL") == 0
                      and sum(1 for s, _, _ in jc.values() if s == "FAIL") == 0)]
    if m7_winners:
        print(f"\n\n### {len(m7_winners)} mode 7 candidates pass ALL invariants ###")
        for n, r, c, jc in m7_winners:
            print_mode_report(f"Mode 7 winner: {n}", r, checks={**c, **jc})
    else:
        # Print best near-pass candidates (lowest fail count)
        m7_results.sort(key=lambda x: sum(1 for s, _, _ in x[2].values() if s == "FAIL")
                                  + sum(1 for s, _, _ in x[3].values() if s == "FAIL"))
        print(f"\n\n### Top 3 mode 7 candidates by fail count ###")
        for n, r, c, jc in m7_results[:3]:
            print_mode_report(f"Mode 7 near-pass: {n}", r, checks={**c, **jc})

    # ============================================================
    # MODE 2
    # ============================================================
    print("\n\n" + "=" * 80)
    print("MODE 2 candidates (lucky, RTP target 300%)")
    print("=" * 80)

    m2_candidates = [
        ("M2_A_central_lucky", M2_A_central_lucky()),
        ("M2_B_higher_h7_central", M2_B_higher_h7_central()),
        ("M2_C_classic_lucky", M2_C_classic_lucky()),
        ("M2_D_higher_h7", M2_D_higher_h7()),
        ("M2_E_higher_RTP", M2_E_higher_RTP()),
        ("M2_F_high_cherry", M2_F_high_cherry()),
        ("M2_G_central_high_cherry", M2_G_central_high_cherry()),
        ("M2_H_aggressive_bars_cherry", M2_H_aggressive_bars_cherry()),
        ("M2_I_h7_anchor", M2_I_h7_anchor()),
        ("M2_J_balanced_high", M2_J_balanced_high()),
        ("M2_K_balanced_high_v2", M2_K_balanced_high_v2()),
        ("M2_L_uneven_dd", M2_L_uneven_dd()),
        ("M2_M_uneven_dd_high_cherry", M2_M_uneven_dd_high_cherry()),
        ("M2_N_uneven_dd_strong_h7", M2_N_uneven_dd_strong_h7()),
        ("M2_O_aggressive_uneven", M2_O_aggressive_uneven()),
        ("M2_P_max_uneven_dd", M2_P_max_uneven_dd()),
        ("M2_Q_h7_max_uneven_dd", M2_Q_h7_max_uneven_dd()),
        ("M2_R_balanced_max", M2_R_balanced_max()),
        ("M2_S_target_300", M2_S_target_300()),
    ]
    m2_results = []
    for name, margs in m2_candidates:
        r = evaluate(margs, 2)
        checks = check_mode2(r, M1_RESULT)
        jchecks = jackpot_check(r)
        m2_results.append((name, r, checks, jchecks))
        n_fail = sum(1 for s, _, _ in checks.values() if s == "FAIL")
        n_jp_fail = sum(1 for s, _, _ in jchecks.values() if s == "FAIL")
        print(f"\n--- {name}: RTP={r['total_rtp_pct']:.2f}pp hit_base={r['base_hit_pct']:.2f}% "
              f"trigger={r['trigger_pct']:.2f}% n_fail={n_fail} n_jp_fail={n_jp_fail} ---")

    m2_winners = [(n, r, c, jc) for (n, r, c, jc) in m2_results
                  if (sum(1 for s, _, _ in c.values() if s == "FAIL") == 0
                      and sum(1 for s, _, _ in jc.values() if s == "FAIL") == 0)]
    if m2_winners:
        print(f"\n\n### {len(m2_winners)} mode 2 candidates pass ALL invariants ###")
        for n, r, c, jc in m2_winners:
            print_mode_report(f"Mode 2 winner: {n}", r, checks={**c, **jc})
    else:
        m2_results.sort(key=lambda x: sum(1 for s, _, _ in x[2].values() if s == "FAIL")
                                  + sum(1 for s, _, _ in x[3].values() if s == "FAIL"))
        print(f"\n\n### Top 3 mode 2 candidates by fail count ###")
        for n, r, c, jc in m2_results[:3]:
            print_mode_report(f"Mode 2 near-pass: {n}", r, checks={**c, **jc})

    # ============================================================
    # MODE 5 (depends on which mode 2 we pick)
    # ============================================================
    # Use top mode 2 candidate as base
    m2_results.sort(key=lambda x: sum(1 for s, _, _ in x[2].values() if s == "FAIL")
                              + sum(1 for s, _, _ in x[3].values() if s == "FAIL"))
    best_m2 = m2_results[0]
    print(f"\n\n=== Selected base for Mode 5 design: {best_m2[0]} ===")
    selected_m2 = best_m2[1]

    print("\n\n" + "=" * 80)
    print("MODE 5 candidates (super-lucky, RTP target 500%)")
    print("=" * 80)

    m5_candidates = [
        ("M5_A_from_M2_E", M5_A_classic_from_M2_E()),
        ("M5_B_from_M2_G", M5_B_modest_lift_from_M2_G()),
        ("M5_C_from_M2_L", M5_C_from_M2_L()),
        ("M5_D_from_M2_O", M5_D_from_M2_O()),
        ("M5_E_modest_M2_O", M5_E_modest_from_M2_O()),
        ("M5_F_from_M2_N", M5_F_from_M2_N()),
        ("M5_G_from_M2_M", M5_G_from_M2_M()),
        ("M5_H_from_M2_Q", M5_H_from_M2_Q()),
        ("M5_I_modest_M2_Q", M5_I_modest_from_M2_Q()),
        ("M5_J_aggressive_M2_Q", M5_J_aggressive_from_M2_Q()),
        ("M5_K_from_M2_S", M5_K_from_M2_S()),
    ]
    m5_results = []
    for name, margs in m5_candidates:
        r = evaluate(margs, 5)
        checks = check_mode5(r, selected_m2, M1_RESULT)
        jchecks = jackpot_check(r)
        m5_results.append((name, r, checks, jchecks))
        n_fail = sum(1 for s, _, _ in checks.values() if s == "FAIL")
        n_jp_fail = sum(1 for s, _, _ in jchecks.values() if s == "FAIL")
        print(f"\n--- {name}: RTP={r['total_rtp_pct']:.2f}pp hit_base={r['base_hit_pct']:.2f}% "
              f"trigger={r['trigger_pct']:.3f}% n_fail={n_fail} n_jp_fail={n_jp_fail} ---")

    m5_winners = [(n, r, c, jc) for (n, r, c, jc) in m5_results
                  if (sum(1 for s, _, _ in c.values() if s == "FAIL") == 0
                      and sum(1 for s, _, _ in jc.values() if s == "FAIL") == 0)]
    if m5_winners:
        print(f"\n\n### {len(m5_winners)} mode 5 candidates pass ALL invariants ###")
        for n, r, c, jc in m5_winners:
            print_mode_report(f"Mode 5 winner: {n}", r, checks={**c, **jc})
    else:
        m5_results.sort(key=lambda x: sum(1 for s, _, _ in x[2].values() if s == "FAIL")
                                  + sum(1 for s, _, _ in x[3].values() if s == "FAIL"))
        print(f"\n\n### Top 3 mode 5 candidates by fail count ###")
        for n, r, c, jc in m5_results[:3]:
            print_mode_report(f"Mode 5 near-pass: {n}", r, checks={**c, **jc})

    print("\n\n=========== END SWEEP ===========")
    print(f"Mode 1 (baseline): RTP={M1_RESULT['total_rtp_pct']:.2f}pp hit={M1_RESULT['base_hit_pct']:.2f}%")
    print(f"M1 trigger: {M1_RESULT['trigger_pct']:.4f}% (1 in {1/M1_RESULT['trigger']:.0f})")
    print(f"M1 wild_pure cadence: 1/{M1_RESULT['wild_cadence']:.0f}")
    print(f"Feature EV by mode: m1={FEAT_BY_MODE[1]['ev']:.2f}× m7={FEAT_BY_MODE[7]['ev']:.2f}× "
          f"m2={FEAT_BY_MODE[2]['ev']:.2f}× m5={FEAT_BY_MODE[5]['ev']:.2f}×")
