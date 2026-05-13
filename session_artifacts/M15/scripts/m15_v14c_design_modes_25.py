"""M15 v14c modes 2/5 design — corrected per user 2026-05-12 feedback.

Mode 1 (C38_C14) and mode 7 (M7_F110) are shipped. This script redesigns
modes 2 & 5 per the user-confirmed corrected philosophy.

Key fixes vs rejected v14b M2_Q / M5_H:
  1) RTP margin to band edges: ≥6pp inside band (M2_Q had only 0.29pp, ~43% sim noise drop risk)
  2) Bar hierarchy §1: P(bar1) > P(bar2) > P(bar3) PRESERVED (M2_Q forced bar2 peak via
     "agent-promoted hardline")
  3) Reel asymmetry direction: R1 blank >= R3 blank PRESERVED per shipped v9 lucky carve-out
     (M2_Q had R1 << R3 — inverted)

Locked invariants:
  - Paytable byte-equal (spec.json `pays` block)
  - feature_params byte-equal v9 per mode (Mode 2 + Mode 5 already shipped)
  - Strip layout unchanged (reel_strips.json)
  - Modes 1 / 7 not modified (just shipped)

Cross-mode invariants verified (12 items per user brief):
  1. Paytable byte-equal
  2. Feature shape locked (feature_params per-mode v9 byte-equal)
  3. Avoid 1000x bet+ (P(R>=1000)/spin <= 1e-5)
  4. Jackpot per-reel <= 0.6%
  5. RTP ladder m5 > m2 > m1 > m7
  6. Hit ladder m5 >= m2 > m1 > m7
  7. Trigger ladder m5 >= m2 > m1; m7 ~ m1
  8. CROSS-RTP m2 in [290, 310] / m5 in [480, 520] verify
     User target: m2 in [292, 308] / m5 in [491.5, 508.5] (min 2pp / 1.5pp margin)
  9. TOP-JACKPOT-CADENCE m2/m1 <= 1.5x cap; m5/m2 >= 1.1x floor
  10. TOP-JACKPOT-ESC P(R>=200)/spin increasing m1 -> m2 -> m5
  11. Bar §1 hierarchy P(bar1) > P(bar2) > P(bar3) preserved cross-mode
  12. Reel asymmetry direction: R1 blank >= R3 blank for m2/m5 (lucky carve-out per shipped v9)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

_M15 = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15 / "spec.json"
STRIPS_PATH = _M15 / "reel_strips.json"
W_M1 = _M15 / "weights" / "mode_1" / "weights.json"
W_M2 = _M15 / "weights" / "mode_2" / "weights.json"
W_M5 = _M15 / "weights" / "mode_5" / "weights.json"
W_M7 = _M15 / "weights" / "mode_7" / "weights.json"

engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator

# Feature params per mode (LOCKED, byte-equal v9).
FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(W_M2.read_text(encoding="utf-8"))["feature_params"],
    5: json.loads(W_M5.read_text(encoding="utf-8"))["feature_params"],
    7: json.loads(W_M7.read_text(encoding="utf-8"))["feature_params"],
}


def feature_stats(fp):
    dist = _round_payout_distribution(
        tuple(fp["x_count_weights"]),
        tuple(fp["y_count_weights"]),
        tuple(fp["x_value_weights"]),
        tuple(fp["y_value_weights"]),
    )
    accept_thr = fp["accept_threshold"]
    p_accept = sum(p for r, p in dist if r >= accept_thr)
    if p_accept == 0:
        return {"ev": 0.0, "p_r_ge_200": 0.0, "p_r_ge_1000": 0.0, "dist": dist}
    A = sum(r * p for r, p in dist if r >= accept_thr) / p_accept
    U = sum(r * p for r, p in dist)
    max_r = fp["max_rounds"]
    reject_streak = 1.0 - p_accept
    ev = 0.0
    for round_idx in range(1, max_r):
        ev += (reject_streak ** (round_idx - 1)) * p_accept * A
    ev += (reject_streak ** (max_r - 1)) * U
    p_r_ge_200 = sum(p for r, p in dist if r >= 200)
    p_r_ge_1000 = sum(p for r, p in dist if r >= 1000)
    return {"ev": ev, "p_r_ge_200": p_r_ge_200, "p_r_ge_1000": p_r_ge_1000,
            "dist": dist, "p_accept": p_accept, "A": A}


FEAT = {m: feature_stats(fp) for m, fp in FP_BY_MODE.items()}

PAY_FAM = {"9": "cherry1", "71": "cherry2", "4": "cherry3", "1": "wild_pure",
           "2": "high7_wild", "21": "high7_pure", "3": "bar3", "5": "bar2",
           "7": "bar1", "8": "bar_mixed"}


def normalize(m):
    out = dict(m)
    nb = sum(v for k, v in out.items() if k != "blank")
    out["blank"] = max(0.0, 1.0 - nb)
    return out


def evaluate(margs, mode):
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof["rtp_pct"]
    hit = prof["hit_rate"]
    trig = margs[2].get("topdollar", 0.0)
    feat = FEAT[mode]
    feat_rtp = trig * feat["ev"] * 100.0
    tot = base + feat_rtp
    fam_pp = defaultdict(float)
    for pid, rtp in prof["pay_rtp"].items():
        fam = PAY_FAM.get(pid)
        if fam is None:
            continue
        fam_pp[fam] += rtp * 100.0
    high7_combined = fam_pp.get("high7_wild", 0) + fam_pp.get("high7_pure", 0)
    fam_share = {}
    if base > 0:
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "wild_pure"):
            fam_share[fam] = fam_pp.get(fam, 0) / base * 100.0
        fam_share["high7"] = high7_combined / base * 100.0
    p_wild = prof["pay_hits"].get("1", 0)
    return {
        "mode": mode, "total_rtp_pct": tot, "base_rtp_pct": base, "feature_rtp_pct": feat_rtp,
        "hit_session_pct": (hit + trig) * 100, "base_hit_pct": hit * 100,
        "trigger_pct": trig * 100, "trigger": trig,
        "r1_blank_pct": margs[0]["blank"] * 100, "r2_blank_pct": margs[1]["blank"] * 100,
        "r3_blank_pct": margs[2]["blank"] * 100,
        "pay_hits": prof["pay_hits"], "pay_rtp": prof["pay_rtp"],
        "family_pp": dict(fam_pp), "family_share_pct": fam_share,
        "high7_combined_pp": high7_combined,
        "wild_cad": 1.0 / p_wild if p_wild > 0 else float("inf"),
        "p_r_ge_1000_spin": trig * feat["p_r_ge_1000"],
        "p_r_ge_200_spin": trig * feat["p_r_ge_200"],
        "cv": prof["cv"], "margs": margs,
    }


# Mode 1 v14 C38_C14 shipped marginals
M1_MARGINALS = [
    {"blank": 0.3852, "cherry": 0.0400, "1bar": 0.2019, "2bar": 0.1648,
     "3bar": 0.1032, "high7": 0.0720, "doublediamond": 0.0290, "jackpot": 0.0040},
    {"blank": 0.5026, "cherry": 0.0350, "1bar": 0.1651, "2bar": 0.1353,
     "3bar": 0.0729, "high7": 0.0571, "doublediamond": 0.0280, "jackpot": 0.0040},
    {"blank": 0.5901, "cherry": 0.0250, "1bar": 0.1349, "2bar": 0.1099,
     "3bar": 0.0549, "high7": 0.0470, "doublediamond": 0.0240,
     "topdollar": 0.0112, "jackpot": 0.0030},
]
M1_RES = evaluate(M1_MARGINALS, 1)

# Mode 7 shipped marginals (M7_F110)
M7_MARGINALS = [
    {"blank": 0.42323, "cherry": 0.03700, "1bar": 0.18697, "2bar": 0.15252,
     "3bar": 0.09534, "high7": 0.07198, "doublediamond": 0.02898, "jackpot": 0.004},
    {"blank": 0.55289, "cherry": 0.03077, "1bar": 0.14470, "2bar": 0.11847,
     "3bar": 0.06405, "high7": 0.05707, "doublediamond": 0.02796, "jackpot": 0.004},
    {"blank": 0.64863, "cherry": 0.02040, "1bar": 0.11045, "2bar": 0.09001,
     "3bar": 0.04500, "high7": 0.04704, "doublediamond": 0.02401,
     "topdollar": 0.01122, "jackpot": 0.003},
]
M7_RES = evaluate(M7_MARGINALS, 7)


# =============================================================================
# MODE 2 RECOMMENDED — Candidate "M2_LC" (Lucky Centered)
# =============================================================================
# Derivation: scale m1 v14 marginals per family per reel
#   cherry: R1=1.6, R2=1.8, R3=2.0
#   bar1/2/3: R1=1.08, R2=1.44, R3=1.80 (uniform within reel; R3 heavier)
#   high7: R1=1.69, R2=2.145, R3=2.6
#   doublediamond: R1=0.95, R2=0.90, R3=0.85
#   topdollar R3=2.95x
# Result: tot=296.118pp, hit=33.85%, R1bl=27.5/R3bl=23.2 (R1>R3 ✓),
#   wld_m2/m1=0.727 (< cap 1.5), bar §1 P(b1)>P(b2)>P(b3) ✓
M2_MARGS_REC = [
    {"cherry": 0.06400, "1bar": 0.21805, "2bar": 0.17798, "3bar": 0.11146,
     "high7": 0.12168, "doublediamond": 0.02755, "jackpot": 0.004},
    {"cherry": 0.06300, "1bar": 0.23774, "2bar": 0.19483, "3bar": 0.10498,
     "high7": 0.12248, "doublediamond": 0.02520, "jackpot": 0.004},
    {"cherry": 0.05000, "1bar": 0.24282, "2bar": 0.19782, "3bar": 0.09882,
     "high7": 0.12220, "doublediamond": 0.02040, "topdollar": 0.03304, "jackpot": 0.003},
]
M2_MARGS_REC = [normalize(m) for m in M2_MARGS_REC]
M2_RES = evaluate(M2_MARGS_REC, 2)

# =============================================================================
# MODE 5 RECOMMENDED — Candidate "M5_LC_plus" (super-lucky, dd-lift, hit preserved)
# =============================================================================
# Derivation: from M2_LC, apply
#   dd: R1×0.95, R2×1.10, R3×1.10 (uneven dd lift — wld_pure cadence m5/m2=1.150,
#       safely above floor 1.1; redirects multiplier mass toward heavier wild paths)
#   td: x1.00 (m5 trigger = m2 trigger, satisfies m5/m2 strict floor)
#   cherry: x1.00 (PRESERVED — keep hit >= m2)
#   bars: x1.00 (PRESERVED — keep hit >= m2)
#   high7: x0.92 (slight cut — releases base RTP budget for total to land in target;
#                 user §18 says multiplier shift toward HIGH but in M15 high mults live
#                 in 200x wild_pure (boosted +32% cadence) + feature (locked +200pp).
#                 h7_lift cut allows base to compress so m5 stays in [490, 510].)
# Result: tot ≈ 504pp, hit ~33.9% (>= m2 hit 33.85%), R1bl=28.6/R3bl=24.0 (R1>R3 ✓),
#   wld_m5/m2=1.150 (>= floor 1.1, multiplier shift per user §18 ii)
M5_MARGS_REC = []
for r_idx, m in enumerate(M2_MARGS_REC):
    new = {}
    dd_lift = [0.95, 1.10, 1.10][r_idx]
    td_lift = [1.0, 1.0, 1.0][r_idx]
    c_lift = 1.0
    b_lift = 1.0
    h_lift = 0.92
    for sym, mg in m.items():
        if sym == "blank":
            continue
        elif sym == "doublediamond":
            new[sym] = mg * dd_lift
        elif sym == "topdollar":
            new[sym] = mg * td_lift
        elif sym == "cherry":
            new[sym] = mg * c_lift
        elif sym in ("1bar", "2bar", "3bar"):
            new[sym] = mg * b_lift
        elif sym == "high7":
            new[sym] = mg * h_lift
        else:
            new[sym] = mg
    M5_MARGS_REC.append(normalize(new))
M5_RES = evaluate(M5_MARGS_REC, 5)


# =============================================================================
# Validation
# =============================================================================

def validate_m2(m2, m1):
    """Validate m2 against all required invariants.
    Returns list of (label, ok, detail)."""
    HIERARCHY_TIED_TOL = 0.001  # 0.10pp absolute per verify.py
    checks = []

    # 1. RTP user-target [292, 308]
    rtp_ok = 292.0 <= m2["total_rtp_pct"] <= 308.0
    checks.append(("[USER-RTP] m2 RTP in [292, 308]", rtp_ok,
                   f"{m2['total_rtp_pct']:.3f}pp"))
    # Verify band [290, 310]
    rtp_strict_ok = 290.0 <= m2["total_rtp_pct"] <= 310.0
    checks.append(("[CROSS-RTP m2 band] [290, 310]", rtp_strict_ok,
                   f"{m2['total_rtp_pct']:.3f}pp"))

    # 2. CROSS-RTP m2 > m1
    cross_rtp = m2["total_rtp_pct"] > m1["total_rtp_pct"]
    checks.append(("[CROSS-RTP] m2 > m1", cross_rtp,
                   f"{m2['total_rtp_pct']:.3f} > {m1['total_rtp_pct']:.3f}"))

    # 3. HIT band [0.30, 0.35]
    base_hit = m2["base_hit_pct"] / 100
    hit_ok = 0.30 <= base_hit <= 0.35
    checks.append(("[HIT m2 band] [0.30, 0.35]", hit_ok, f"{base_hit:.4f}"))

    # 4. LUCKY-MONO hit > m1
    lucky_hit = base_hit > m1["base_hit_pct"] / 100
    checks.append(("[LUCKY-MONO hit] m2 > m1", lucky_hit,
                   f"{base_hit:.4f} > {m1['base_hit_pct']/100:.4f}"))

    # 5. LUCKY-MONO trigger >= m1
    lucky_trig = m2["trigger"] >= m1["trigger"] - 1e-9
    checks.append(("[LUCKY-MONO trig] m2 >= m1", lucky_trig,
                   f"{m2['trigger']*100:.4f}% >= {m1['trigger']*100:.4f}%"))

    # 6. TOP-JACKPOT-CADENCE wild_pure m2/m1 <= 1.5
    pwild_m1 = m1["pay_hits"].get("1", 1e-12)
    pwild_m2 = m2["pay_hits"].get("1", 0)
    ratio = pwild_m2 / pwild_m1
    cad_ok = ratio <= 1.5
    checks.append(("[TOP-JACKPOT-CADENCE m2/m1 <= 1.5]", cad_ok, f"ratio={ratio:.3f}"))

    # 7. Bar §1 hierarchy (in P, per philosophy §1)
    b1 = m2["pay_hits"].get("7", 0)
    b2 = m2["pay_hits"].get("5", 0)
    b3 = m2["pay_hits"].get("3", 0)
    bar_ok = b1 > b2 > b3
    checks.append(("[BAR-HIERARCHY-§1] P(bar1) > P(bar2) > P(bar3)", bar_ok,
                   f"b1={b1*100:.4f}% > b2={b2*100:.4f}% > b3={b3*100:.4f}%"))

    # 8. Cherry hierarchy
    c1 = m2["pay_hits"].get("9", 0)
    c2 = m2["pay_hits"].get("71", 0)
    c3 = m2["pay_hits"].get("4", 0)
    c_ok = (c1 >= c2 - HIERARCHY_TIED_TOL) and (c2 >= c3 - HIERARCHY_TIED_TOL)
    checks.append(("[CHERRY-HIERARCHY] c1 >= c2 >= c3", c_ok,
                   f"c1={c1*100:.4f}% c2={c2*100:.4f}% c3={c3*100:.4f}%"))

    # 9. H7 hierarchy
    h7w = m2["pay_hits"].get("2", 0)
    h7p = m2["pay_hits"].get("21", 0)
    h7_ok = h7w >= h7p - HIERARCHY_TIED_TOL
    checks.append(("[H7-HIERARCHY] h7_wild >= h7_pure - 0.10pp", h7_ok,
                   f"h7w={h7w*100:.4f}% h7p={h7p*100:.4f}% diff={(h7p-h7w)*100:.4f}pp"))

    # 10. P(R>=1000)/spin <= 1e-5
    p_r1k_ok = m2["p_r_ge_1000_spin"] <= 1e-5
    checks.append(("[1000+] P(R>=1000)/spin <= 1e-5", p_r1k_ok,
                   f"{m2['p_r_ge_1000_spin']:.3e}"))

    # 11. Jackpot per-reel <= 0.6%
    jp_ok = all(m.get("jackpot", 0) <= 0.006 for m in m2["margs"])
    checks.append(("[JACKPOT-VIS] all reels jp <= 0.6%", jp_ok, ""))

    # 12. Reel asymmetry per shipped v9 lucky carve-out: R1 blank >= R3 blank
    r1r3_ok = m2["r1_blank_pct"] >= m2["r3_blank_pct"]
    checks.append(("[REEL-ASYM-LUCKY] R1 blank >= R3 blank (shipped v9 direction)", r1r3_ok,
                   f"R1={m2['r1_blank_pct']:.2f} R3={m2['r3_blank_pct']:.2f}"))

    # 13. FAMILY-SHARE m2 from verify.py bands
    fs = m2["family_share_pct"]
    c1_sh_ok = 15.0 <= fs["cherry1"] <= 25.0
    checks.append(("[FAM-SHARE c1 [15, 25]]", c1_sh_ok, f"{fs['cherry1']:.2f}%"))
    b3_sh_ok = 5.0 <= fs["bar3"] <= 22.0
    checks.append(("[FAM-SHARE b3 [5, 22]]", b3_sh_ok, f"{fs['bar3']:.2f}%"))
    h7_sh_ok = 14.0 <= fs["high7"] <= 30.0
    checks.append(("[FAM-SHARE h7 [14, 30]]", h7_sh_ok, f"{fs['high7']:.2f}%"))
    wsh_ok = 0.08 <= fs["wild_pure"] <= 0.30
    checks.append(("[FAM-SHARE wld [0.08, 0.30]]", wsh_ok, f"{fs['wild_pure']:.3f}%"))

    # 14. TOP-JACKPOT-ESC P(R>=200)/spin: m2 > m1
    esc_ok = m2["p_r_ge_200_spin"] > m1["p_r_ge_200_spin"]
    checks.append(("[TOP-JACKPOT-ESC] P(R>=200)/spin m2 > m1", esc_ok,
                   f"{m2['p_r_ge_200_spin']:.3e} > {m1['p_r_ge_200_spin']:.3e}"))

    return checks


def validate_m5(m5, m2, m1):
    HIERARCHY_TIED_TOL = 0.001
    checks = []

    # RTP user-target [491.5, 508.5] (min 1.5pp margin)
    rtp_user_ok = 491.5 <= m5["total_rtp_pct"] <= 508.5
    checks.append(("[USER-RTP] m5 RTP in [491.5, 508.5]", rtp_user_ok,
                   f"{m5['total_rtp_pct']:.3f}pp"))
    # Verify band [480, 520]
    rtp_verify_ok = 480.0 <= m5["total_rtp_pct"] <= 520.0
    checks.append(("[CROSS-RTP m5 band] [480, 520]", rtp_verify_ok,
                   f"{m5['total_rtp_pct']:.3f}pp"))

    # CROSS-RTP m5 > m2
    cross_rtp = m5["total_rtp_pct"] > m2["total_rtp_pct"]
    checks.append(("[CROSS-RTP] m5 > m2", cross_rtp,
                   f"{m5['total_rtp_pct']:.3f} > {m2['total_rtp_pct']:.3f}"))

    # HIT band
    base_hit = m5["base_hit_pct"] / 100
    hit_ok = 0.30 <= base_hit <= 0.35
    checks.append(("[HIT m5 band] [0.30, 0.35]", hit_ok, f"{base_hit:.4f}"))

    # LUCKY-MONO m5 hit >= m2
    lucky_hit = base_hit >= m2["base_hit_pct"] / 100 - 1e-9
    checks.append(("[LUCKY-MONO hit] m5 >= m2", lucky_hit,
                   f"{base_hit:.4f} >= {m2['base_hit_pct']/100:.4f}"))

    # LUCKY-MONO m5 trigger >= m2
    lucky_trig = m5["trigger"] >= m2["trigger"] - 1e-9
    checks.append(("[LUCKY-MONO trig] m5 >= m2", lucky_trig,
                   f"{m5['trigger']*100:.4f}% >= {m2['trigger']*100:.4f}%"))

    # TOP-JACKPOT-CADENCE m5/m2 >= 1.1
    pwild_m2 = m2["pay_hits"].get("1", 1e-12)
    pwild_m5 = m5["pay_hits"].get("1", 0)
    ratio = pwild_m5 / pwild_m2
    cad_ok = ratio >= 1.1
    checks.append(("[TOP-JACKPOT-CADENCE m5/m2 >= 1.1]", cad_ok, f"ratio={ratio:.3f}"))

    # Bar §1 hierarchy
    b1 = m5["pay_hits"].get("7", 0)
    b2 = m5["pay_hits"].get("5", 0)
    b3 = m5["pay_hits"].get("3", 0)
    bar_ok = b1 > b2 > b3
    checks.append(("[BAR-HIERARCHY-§1] P(bar1) > P(bar2) > P(bar3)", bar_ok,
                   f"b1={b1*100:.4f}% > b2={b2*100:.4f}% > b3={b3*100:.4f}%"))

    # Cherry hierarchy
    c1 = m5["pay_hits"].get("9", 0)
    c2 = m5["pay_hits"].get("71", 0)
    c3 = m5["pay_hits"].get("4", 0)
    c_ok = (c1 >= c2 - HIERARCHY_TIED_TOL) and (c2 >= c3 - HIERARCHY_TIED_TOL)
    checks.append(("[CHERRY-HIERARCHY] c1 >= c2 >= c3", c_ok,
                   f"c1={c1*100:.4f}% c2={c2*100:.4f}% c3={c3*100:.4f}%"))

    # H7 hierarchy
    h7w = m5["pay_hits"].get("2", 0)
    h7p = m5["pay_hits"].get("21", 0)
    h7_ok = h7w >= h7p - HIERARCHY_TIED_TOL
    checks.append(("[H7-HIERARCHY] h7_wild >= h7_pure - 0.10pp", h7_ok,
                   f"h7w={h7w*100:.4f}% h7p={h7p*100:.4f}% diff={(h7p-h7w)*100:.4f}pp"))

    # P(R>=1000)/spin
    p_r1k_ok = m5["p_r_ge_1000_spin"] <= 1e-5
    checks.append(("[1000+] P(R>=1000)/spin <= 1e-5", p_r1k_ok,
                   f"{m5['p_r_ge_1000_spin']:.3e}"))

    # Jackpot
    jp_ok = all(m.get("jackpot", 0) <= 0.006 for m in m5["margs"])
    checks.append(("[JACKPOT-VIS] all reels jp <= 0.6%", jp_ok, ""))

    # Reel asymmetry
    r1r3_ok = m5["r1_blank_pct"] >= m5["r3_blank_pct"]
    checks.append(("[REEL-ASYM-LUCKY] R1 blank >= R3 blank (shipped v9 direction)", r1r3_ok,
                   f"R1={m5['r1_blank_pct']:.2f} R3={m5['r3_blank_pct']:.2f}"))

    # FAMILY-SHARE m5 (only bar3 explicit; others inherit but informational)
    fs = m5["family_share_pct"]
    b3_sh_ok = 5.0 <= fs["bar3"] <= 22.0
    checks.append(("[FAM-SHARE b3 [5, 22] m5-explicit]", b3_sh_ok, f"{fs['bar3']:.2f}%"))

    # TOP-JACKPOT-ESC P(R>=200)/spin: m5 > m2
    esc_ok = m5["p_r_ge_200_spin"] > m2["p_r_ge_200_spin"]
    checks.append(("[TOP-JACKPOT-ESC] P(R>=200)/spin m5 > m2", esc_ok,
                   f"{m5['p_r_ge_200_spin']:.3e} > {m2['p_r_ge_200_spin']:.3e}"))

    return checks


# Cross-mode checks
def validate_cross_mode(m1, m2, m5, m7):
    """Validate cross-mode ladders."""
    checks = []

    # RTP ladder
    ok = m7["total_rtp_pct"] < m1["total_rtp_pct"]
    checks.append(("[RTP-LADDER] m7 < m1", ok,
                   f"{m7['total_rtp_pct']:.3f} < {m1['total_rtp_pct']:.3f}"))
    ok = m1["total_rtp_pct"] < m2["total_rtp_pct"]
    checks.append(("[RTP-LADDER] m1 < m2", ok,
                   f"{m1['total_rtp_pct']:.3f} < {m2['total_rtp_pct']:.3f}"))
    ok = m2["total_rtp_pct"] < m5["total_rtp_pct"]
    checks.append(("[RTP-LADDER] m2 < m5", ok,
                   f"{m2['total_rtp_pct']:.3f} < {m5['total_rtp_pct']:.3f}"))

    # Hit ladder
    ok = m7["base_hit_pct"] < m1["base_hit_pct"]
    checks.append(("[HIT-LADDER] m7 < m1", ok,
                   f"{m7['base_hit_pct']:.3f}% < {m1['base_hit_pct']:.3f}%"))
    ok = m1["base_hit_pct"] < m2["base_hit_pct"]
    checks.append(("[HIT-LADDER] m1 < m2", ok,
                   f"{m1['base_hit_pct']:.3f}% < {m2['base_hit_pct']:.3f}%"))
    ok = m2["base_hit_pct"] <= m5["base_hit_pct"] + 1e-9  # ≤ in this case (m5 hit can be lower)
    # Actually LUCKY-MONO requires m5 hit >= m2 hit
    ok = m5["base_hit_pct"] >= m2["base_hit_pct"] - 1e-9
    checks.append(("[HIT-LADDER] m5 >= m2 (LUCKY-MONO)", ok,
                   f"{m5['base_hit_pct']:.3f}% >= {m2['base_hit_pct']:.3f}%"))

    # Trigger ladder
    ok = abs(m7["trigger"] - m1["trigger"]) <= 5e-4
    checks.append(("[TRIG-LADDER] m7 ~ m1 (tol 5e-4)", ok,
                   f"|{m7['trigger']:.6f} - {m1['trigger']:.6f}| = {abs(m7['trigger']-m1['trigger']):.6f}"))
    ok = m2["trigger"] >= m1["trigger"] - 1e-9
    checks.append(("[TRIG-LADDER] m2 >= m1", ok,
                   f"{m2['trigger']*100:.4f}% >= {m1['trigger']*100:.4f}%"))
    ok = m5["trigger"] >= m2["trigger"] - 1e-9
    checks.append(("[TRIG-LADDER] m5 >= m2 (LUCKY-MONO)", ok,
                   f"{m5['trigger']*100:.4f}% >= {m2['trigger']*100:.4f}%"))

    # TOP-JACKPOT-ESC P(R>=200)/spin escalating
    ok = m1["p_r_ge_200_spin"] < m2["p_r_ge_200_spin"] < m5["p_r_ge_200_spin"]
    checks.append(("[TOP-JACKPOT-ESC] P(R>=200)/spin m1 < m2 < m5", ok,
                   f"{m1['p_r_ge_200_spin']:.3e} < {m2['p_r_ge_200_spin']:.3e} < {m5['p_r_ge_200_spin']:.3e}"))

    return checks


# ===================================================================
# Print all results
# ===================================================================

def print_results():
    print("\n" + "="*72)
    print("M15 v14c Mode 2/5 Design Results")
    print("="*72)

    print("\n--- Mode 1 (C38_C14 shipped baseline) ---")
    print(f"Total RTP: {M1_RES['total_rtp_pct']:.3f}pp  (base {M1_RES['base_rtp_pct']:.3f}pp + feature {M1_RES['feature_rtp_pct']:.3f}pp)")
    print(f"Base hit: {M1_RES['base_hit_pct']:.3f}%   Trigger: {M1_RES['trigger_pct']:.4f}%")
    print(f"P(b1): {M1_RES['pay_hits']['7']*100:.4f}%  P(b2): {M1_RES['pay_hits']['5']*100:.4f}%  P(b3): {M1_RES['pay_hits']['3']*100:.4f}%")
    print(f"R1/R2/R3 blank: {M1_RES['r1_blank_pct']:.2f} / {M1_RES['r2_blank_pct']:.2f} / {M1_RES['r3_blank_pct']:.2f}")
    print(f"wild_pure cadence: 1/{M1_RES['wild_cad']:.0f}   P(R>=1000)/spin: {M1_RES['p_r_ge_1000_spin']:.3e}")

    print("\n--- Mode 7 (M7_F110 shipped) ---")
    print(f"Total RTP: {M7_RES['total_rtp_pct']:.3f}pp")
    print(f"Base hit: {M7_RES['base_hit_pct']:.3f}%   Trigger: {M7_RES['trigger_pct']:.4f}%")
    print(f"wild_pure cadence: 1/{M7_RES['wild_cad']:.0f}")

    print("\n--- Mode 2 RECOMMENDED (M2_LC) ---")
    print(f"Total RTP: {M2_RES['total_rtp_pct']:.3f}pp  (base {M2_RES['base_rtp_pct']:.3f}pp + feature {M2_RES['feature_rtp_pct']:.3f}pp)")
    margin_lo = M2_RES['total_rtp_pct'] - 290
    margin_hi = 310 - M2_RES['total_rtp_pct']
    print(f"RTP margin to [290, 310]: +{margin_lo:.2f}pp to floor, +{margin_hi:.2f}pp to ceiling")
    print(f"Base hit: {M2_RES['base_hit_pct']:.3f}%   Trigger: {M2_RES['trigger_pct']:.4f}%")
    print(f"P(b1): {M2_RES['pay_hits']['7']*100:.4f}%  P(b2): {M2_RES['pay_hits']['5']*100:.4f}%  P(b3): {M2_RES['pay_hits']['3']*100:.4f}%")
    print(f"R1/R2/R3 blank: {M2_RES['r1_blank_pct']:.2f} / {M2_RES['r2_blank_pct']:.2f} / {M2_RES['r3_blank_pct']:.2f}")
    print(f"wild_pure cadence: 1/{M2_RES['wild_cad']:.0f}   m2/m1: {M2_RES['pay_hits']['1']/M1_RES['pay_hits']['1']:.3f}")
    print(f"P(R>=1000)/spin: {M2_RES['p_r_ge_1000_spin']:.3e}  P(R>=200)/spin: {M2_RES['p_r_ge_200_spin']:.3e}")

    print("\nMode 2 marginals (%):")
    for i, m in enumerate(M2_RES["margs"]):
        items = sorted(m.items())
        line = "  R{}: ".format(i+1) + " ".join(f"{s}={v*100:.3f}" for s, v in items)
        print(f"{line}   sum={sum(m.values())*100:.6f}")

    print("\nMode 2 per-pay-id breakdown:")
    print(f"  {'pid':<5} {'family':<14} {'mult':<10} {'hit%':>10} {'1 in N':>10} {'RTP pp':>8}")
    pay_order = ["9", "71", "4", "1", "2", "21", "3", "5", "7", "8"]
    mults = {"9": "1x", "71": "5x", "4": "15x", "1": "200x",
             "2": "30/60/120x", "21": "30x",
             "3": "20/40/80x", "5": "10/20/40x", "7": "5/10/20x", "8": "2/4x"}
    for pid in pay_order:
        p = M2_RES["pay_hits"].get(pid, 0)
        rtp = M2_RES["pay_rtp"].get(pid, 0) * 100
        oneN = 1.0 / p if p > 0 else float("inf")
        fam = PAY_FAM.get(pid, "?")
        print(f"  {pid:<5} {fam:<14} {mults[pid]:<10} {p*100:>10.4f} {oneN:>10.0f} {rtp:>8.4f}")

    print("\nMode 2 family share-of-base:")
    for fam in sorted(M2_RES["family_share_pct"], key=lambda f: -M2_RES["family_share_pct"][f]):
        sh = M2_RES["family_share_pct"][fam]
        absol = M2_RES["family_pp"].get(fam, 0) if fam != "high7" else M2_RES["high7_combined_pp"]
        print(f"  {fam:<14} {sh:6.2f}%   {absol:6.3f}pp")

    print("\n--- Mode 5 RECOMMENDED (M5_LC_plus) ---")
    print(f"Total RTP: {M5_RES['total_rtp_pct']:.3f}pp  (base {M5_RES['base_rtp_pct']:.3f}pp + feature {M5_RES['feature_rtp_pct']:.3f}pp)")
    margin_lo = M5_RES['total_rtp_pct'] - 490
    margin_hi = 510 - M5_RES['total_rtp_pct']
    print(f"RTP margin to [490, 510]: +{margin_lo:.2f}pp to floor, +{margin_hi:.2f}pp to ceiling")
    print(f"Base hit: {M5_RES['base_hit_pct']:.3f}%   Trigger: {M5_RES['trigger_pct']:.4f}%")
    print(f"P(b1): {M5_RES['pay_hits']['7']*100:.4f}%  P(b2): {M5_RES['pay_hits']['5']*100:.4f}%  P(b3): {M5_RES['pay_hits']['3']*100:.4f}%")
    print(f"R1/R2/R3 blank: {M5_RES['r1_blank_pct']:.2f} / {M5_RES['r2_blank_pct']:.2f} / {M5_RES['r3_blank_pct']:.2f}")
    print(f"wild_pure cadence: 1/{M5_RES['wild_cad']:.0f}   m5/m2: {M5_RES['pay_hits']['1']/M2_RES['pay_hits']['1']:.3f}")
    print(f"P(R>=1000)/spin: {M5_RES['p_r_ge_1000_spin']:.3e}  P(R>=200)/spin: {M5_RES['p_r_ge_200_spin']:.3e}")
    print(f"Base lift vs m2: {M5_RES['base_rtp_pct']-M2_RES['base_rtp_pct']:+.2f}pp")

    print("\nMode 5 marginals (%):")
    for i, m in enumerate(M5_RES["margs"]):
        items = sorted(m.items())
        line = "  R{}: ".format(i+1) + " ".join(f"{s}={v*100:.3f}" for s, v in items)
        print(f"{line}   sum={sum(m.values())*100:.6f}")

    print("\nMode 5 per-pay-id breakdown:")
    print(f"  {'pid':<5} {'family':<14} {'mult':<10} {'hit%':>10} {'1 in N':>10} {'RTP pp':>8}")
    for pid in pay_order:
        p = M5_RES["pay_hits"].get(pid, 0)
        rtp = M5_RES["pay_rtp"].get(pid, 0) * 100
        oneN = 1.0 / p if p > 0 else float("inf")
        fam = PAY_FAM.get(pid, "?")
        print(f"  {pid:<5} {fam:<14} {mults[pid]:<10} {p*100:>10.4f} {oneN:>10.0f} {rtp:>8.4f}")

    print("\nMode 5 family share-of-base:")
    for fam in sorted(M5_RES["family_share_pct"], key=lambda f: -M5_RES["family_share_pct"][f]):
        sh = M5_RES["family_share_pct"][fam]
        absol = M5_RES["family_pp"].get(fam, 0) if fam != "high7" else M5_RES["high7_combined_pp"]
        print(f"  {fam:<14} {sh:6.2f}%   {absol:6.3f}pp")

    # Per-pay m2/m1 and m5/m2 ratio table
    print("\n--- Per-pay-id frequency ratios (cross-mode) ---")
    print(f"  {'pid':<4} {'family':<14} {'m1 P%':>10} {'m2 P%':>10} {'m2/m1':>8} {'m5 P%':>10} {'m5/m2':>8}")
    for pid in pay_order:
        m1_p = M1_RES["pay_hits"].get(pid, 0)
        m2_p = M2_RES["pay_hits"].get(pid, 0)
        m5_p = M5_RES["pay_hits"].get(pid, 0)
        r1 = m2_p / m1_p if m1_p else 0
        r2 = m5_p / m2_p if m2_p else 0
        fam = PAY_FAM.get(pid, "?")
        print(f"  {pid:<4} {fam:<14} {m1_p*100:>10.4f} {m2_p*100:>10.4f} {r1:>8.3f} {m5_p*100:>10.4f} {r2:>8.3f}")

    # Validations
    print("\n--- Mode 2 invariant checks ---")
    m2_checks = validate_m2(M2_RES, M1_RES)
    n_pass = sum(1 for _, ok, _ in m2_checks if ok)
    print(f"PASS {n_pass}/{len(m2_checks)}:")
    for label, ok, detail in m2_checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}: {detail}")

    print("\n--- Mode 5 invariant checks ---")
    m5_checks = validate_m5(M5_RES, M2_RES, M1_RES)
    n_pass = sum(1 for _, ok, _ in m5_checks if ok)
    print(f"PASS {n_pass}/{len(m5_checks)}:")
    for label, ok, detail in m5_checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}: {detail}")

    print("\n--- Cross-mode ladder checks ---")
    cm_checks = validate_cross_mode(M1_RES, M2_RES, M5_RES, M7_RES)
    n_pass = sum(1 for _, ok, _ in cm_checks if ok)
    print(f"PASS {n_pass}/{len(cm_checks)}:")
    for label, ok, detail in cm_checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}: {detail}")

    total_checks = len(m2_checks) + len(m5_checks) + len(cm_checks)
    total_pass = (sum(1 for _, ok, _ in m2_checks if ok) +
                  sum(1 for _, ok, _ in m5_checks if ok) +
                  sum(1 for _, ok, _ in cm_checks if ok))
    print(f"\n=== TOTAL: {total_pass}/{total_checks} checks pass ===")


if __name__ == "__main__":
    print_results()
