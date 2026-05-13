"""M15 v14d mode 5 — INDEPENDENT VERIFIER (2026-05-12).

Verifies D's M5_HMV_plus candidate from design_v14d_mode5.md WITHOUT
importing D's design script. Reconstructs M5 marginals from per-family
scalar applied to shipped M2_LC anchor, recomputes integer per-stop
weights via local primitives, runs analytic_profile_from_marginals,
and exercises verify.py against the resulting temp weights.

Special focus per V brief:
  - LUCKY-MONO hit margin: D claims +0.06pp. Does it survive integer rounding?
  - LUCKY-MONO trigger margin: D claims +0.0165pp. Survives?
  - Bar §1 hierarchy: STRICT > or TIED within 0.10pp tol?
  - Base ≥30× mult share — independent compute. D claims 40.12%.
  - RTP analytic vs engine drift — D claims 508.21pp. Engine likely 0.3-0.7pp lower.
  - All 17 cross-mode invariants checked independently.
  - verify.py REDs classified.

DOES NOT modify production files. Writes temp weights to
`session_artifacts/M15/_tmp_v14d_verify/mode_{1,2,5,7}/weights.json`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    analytic_profile_from_marginals,
)
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
W_M1 = _M15_DIR / "weights" / "mode_1" / "weights.json"
W_M2 = _M15_DIR / "weights" / "mode_2" / "weights.json"
W_M5 = _M15_DIR / "weights" / "mode_5" / "weights.json"
W_M7 = _M15_DIR / "weights" / "mode_7" / "weights.json"

TMP_ROOT = _ROOT / "session_artifacts" / "M15" / "_tmp_v14d_verify"

# ----------------------------------------------------------------------
# Mode 1, mode 2 (M2_LC), mode 7 marginals — from shipped production
# Mode 5 marginals — independently derived from per-family scalar over
# M2_LC anchor (NOT imported from D's script).
# ----------------------------------------------------------------------

# Mode 1 (shipped C38_C14)
M1_R1 = {"blank": 0.3852, "cherry": 0.0400, "1bar": 0.2019, "2bar": 0.1648,
         "3bar": 0.1032, "high7": 0.0720, "doublediamond": 0.0290,
         "jackpot": 0.0040}
M1_R2 = {"blank": 0.5026, "cherry": 0.0350, "1bar": 0.1651, "2bar": 0.1353,
         "3bar": 0.0729, "high7": 0.0571, "doublediamond": 0.0280,
         "jackpot": 0.0040}
M1_R3 = {"blank": 0.5901, "cherry": 0.0250, "1bar": 0.1349, "2bar": 0.1099,
         "3bar": 0.0549, "high7": 0.0470, "doublediamond": 0.0240,
         "topdollar": 0.0112, "jackpot": 0.0030}

# Mode 7 (shipped M7_F110)
M7_R1 = {"blank": 0.42323, "cherry": 0.03700, "1bar": 0.18697, "2bar": 0.15252,
         "3bar": 0.09534, "high7": 0.07198, "doublediamond": 0.02898,
         "jackpot": 0.004}
M7_R2 = {"blank": 0.55289, "cherry": 0.03077, "1bar": 0.14470, "2bar": 0.11847,
         "3bar": 0.06405, "high7": 0.05707, "doublediamond": 0.02796,
         "jackpot": 0.004}
M7_R3 = {"blank": 0.64863, "cherry": 0.02040, "1bar": 0.11045, "2bar": 0.09001,
         "3bar": 0.04500, "high7": 0.04704, "doublediamond": 0.02401,
         "topdollar": 0.01122, "jackpot": 0.003}

# Mode 2 M2_LC (shipped) — non-blank marginals; blank recomputed as residual.
M2_R1 = {"cherry": 0.06400, "1bar": 0.21805, "2bar": 0.17798,
         "3bar": 0.11146, "high7": 0.12168, "doublediamond": 0.02755,
         "jackpot": 0.004}
M2_R2 = {"cherry": 0.06300, "1bar": 0.23774, "2bar": 0.19483,
         "3bar": 0.10498, "high7": 0.12248, "doublediamond": 0.02520,
         "jackpot": 0.004}
M2_R3 = {"cherry": 0.05000, "1bar": 0.24282, "2bar": 0.19782,
         "3bar": 0.09882, "high7": 0.12220, "doublediamond": 0.02040,
         "topdollar": 0.03304, "jackpot": 0.003}


def normalize_margs(d):
    """Recompute blank as residual; sum to 1 exactly."""
    out = dict(d)
    nb = sum(v for k, v in out.items() if k != "blank")
    out["blank"] = max(0.0, 1.0 - nb)
    return out


M1_MARGS = [normalize_margs(M1_R1), normalize_margs(M1_R2), normalize_margs(M1_R3)]
M7_MARGS = [normalize_margs(M7_R1), normalize_margs(M7_R2), normalize_margs(M7_R3)]
M2_MARGS = [normalize_margs(M2_R1), normalize_margs(M2_R2), normalize_margs(M2_R3)]


# ----------------------------------------------------------------------
# Build M5 marginals from per-family scalar (D's candidate).
# c_lift=1.13, b1_lift=0.85, b2_lift=1.03, b3_lift=1.05
# h_lift_r=(1.03, 1.03, 1.03), dd_lift_r=(1.05, 1.05, 1.05), td_lift=1.005
# ----------------------------------------------------------------------

C_LIFT = 1.13
B1_LIFT = 0.85
B2_LIFT = 1.03
B3_LIFT = 1.05
H_LIFT = (1.03, 1.03, 1.03)
DD_LIFT = (1.05, 1.05, 1.05)
TD_LIFT = 1.005

SCALAR_BY_FAM = {
    "cherry": C_LIFT,
    "1bar": B1_LIFT,
    "2bar": B2_LIFT,
    "3bar": B3_LIFT,
    "jackpot": 1.0,
}


def build_m5_from_scalar(m2_margs):
    out = []
    for r_idx, m in enumerate(m2_margs):
        new = {}
        for sym, val in m.items():
            if sym == "blank":
                continue
            elif sym == "doublediamond":
                new[sym] = val * DD_LIFT[r_idx]
            elif sym == "topdollar":
                new[sym] = val * TD_LIFT
            elif sym == "high7":
                new[sym] = val * H_LIFT[r_idx]
            elif sym in SCALAR_BY_FAM:
                new[sym] = val * SCALAR_BY_FAM[sym]
            else:
                new[sym] = val
        nb = sum(new.values())
        new["blank"] = max(0.0, 1.0 - nb)
        out.append(new)
    return out


M5_MARGS = build_m5_from_scalar(M2_MARGS)


# ----------------------------------------------------------------------
# Load engine + strips + per-mode feature_params (LOCKED v9)
# ----------------------------------------------------------------------

engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator
STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(W_M2.read_text(encoding="utf-8"))["feature_params"],
    5: json.loads(W_M5.read_text(encoding="utf-8"))["feature_params"],
    7: json.loads(W_M7.read_text(encoding="utf-8"))["feature_params"],
}


def feature_ev_per_trigger(fp):
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
    reject_streak = 1.0 - p_accept
    ev = 0.0
    for round_idx in range(1, max_r):
        ev += (reject_streak ** (round_idx - 1)) * p_accept * A
    ev += (reject_streak ** (max_r - 1)) * U
    return ev, dist


FEAT_BY_MODE = {}
for mode, fp in FP_BY_MODE.items():
    ev, dist = feature_ev_per_trigger(fp)
    FEAT_BY_MODE[mode] = {
        "ev": ev,
        "dist": dist,
        "p_r_ge_200_per_trigger": sum(p for r, p in dist if r >= 200),
        "p_r_ge_1000_per_trigger": sum(p for r, p in dist if r >= 1000),
    }


# ----------------------------------------------------------------------
# Family / paytable mapping
# ----------------------------------------------------------------------

FAMILY_OF_PAY_ID = {
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

PAY_MULT = {
    "9": 1, "71": 5, "4": 15,
    "1": 200,
    "2": 30, "21": 30,
    "3": 20, "5": 10, "7": 5,
    "8": 2,
}


# ----------------------------------------------------------------------
# marginals_to_weights + apply_mechanism_b_blanks
# ----------------------------------------------------------------------

def marginals_to_weights(strips, margs, scale=10000):
    counts_per_reel = []
    for reel in strips:
        c = defaultdict(int)
        for s in reel:
            c[s] += 1
        counts_per_reel.append(dict(c))
    out = []
    for ri, reel in enumerate(strips):
        target = margs[ri]
        counts = counts_per_reel[ri]
        wps = {}
        for sym, frac in target.items():
            cnt = counts.get(sym, 0)
            if cnt == 0:
                continue
            w = scale * frac / cnt
            wps[sym] = max(1, int(round(w)))
        row = [wps.get(s, 1) for s in reel]
        out.append(row)
    return out


def apply_mechanism_b_blanks(strips, weights,
                             top_symbols=("doublediamond", "high7", "topdollar"),
                             floor=1):
    out = [list(r) for r in weights]
    top = set(top_symbols)
    for ri, reel in enumerate(strips):
        n = len(reel)
        total_blank = sum(out[ri][i] for i in range(n) if reel[i] == "blank")
        top_adj, non_top_adj = [], []
        for i in range(n):
            if reel[i] != "blank":
                continue
            if reel[(i - 1) % n] in top or reel[(i + 1) % n] in top:
                top_adj.append(i)
            else:
                non_top_adj.append(i)
        if not top_adj:
            continue
        reserve = floor * len(non_top_adj)
        leftover = total_blank - reserve
        if leftover <= 0:
            continue
        per = leftover // len(top_adj)
        rem = leftover - per * len(top_adj)
        for i in non_top_adj:
            out[ri][i] = floor
        for k, i in enumerate(top_adj):
            out[ri][i] = per + (1 if k < rem else 0)
    return out


def reel_marginals_from_weights(strips, weights):
    out = []
    for ri, reel in enumerate(strips):
        total = sum(weights[ri])
        c = defaultdict(int)
        for sym, w in zip(reel, weights[ri]):
            c[sym] += w
        out.append({sym: w / total for sym, w in c.items() if w > 0})
    return out


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------

def evaluate(margs, mode, *, tag=""):
    prof = analytic_profile_from_marginals(EV, margs)
    trigger = margs[2].get("topdollar", 0.0)
    base_rtp_pct = prof["rtp_pct"]
    base_hit = prof["hit_rate"]
    feat = FEAT_BY_MODE[mode]
    feature_rtp_pct = trigger * feat["ev"] * 100
    total_rtp_pct = base_rtp_pct + feature_rtp_pct
    hit_session = (base_hit + trigger) * 100
    p_r_ge_1000_per_spin = trigger * feat["p_r_ge_1000_per_trigger"]
    p_r_ge_200_per_spin = trigger * feat["p_r_ge_200_per_trigger"]

    pay_hits = prof["pay_hits"]
    pay_rtp = prof["pay_rtp"]
    family_pp = defaultdict(float)
    for pid, rtp in pay_rtp.items():
        fam = FAMILY_OF_PAY_ID.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp * 100
    high7_combined_pp = family_pp.get("high7_wild", 0) + family_pp.get("high7_pure", 0)
    family_shares = {}
    if base_rtp_pct > 0:
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "wild_pure"):
            family_shares[fam] = family_pp.get(fam, 0) / base_rtp_pct * 100
        family_shares["high7"] = high7_combined_pp / base_rtp_pct * 100

    p_wild = pay_hits.get("1", 0)
    wild_cadence = 1.0 / p_wild if p_wild > 0 else float("inf")

    return {
        "tag": tag,
        "mode": mode,
        "total_rtp": total_rtp_pct,
        "base_rtp": base_rtp_pct,
        "feature_rtp": feature_rtp_pct,
        "hit_session": hit_session,
        "base_hit": base_hit * 100,
        "trigger": trigger * 100,
        "trigger_frac": trigger,
        "r1_blank": margs[0].get("blank", 0) * 100,
        "r2_blank": margs[1].get("blank", 0) * 100,
        "r3_blank": margs[2].get("blank", 0) * 100,
        "pay_hits": pay_hits,
        "pay_rtp": pay_rtp,
        "family_pp": dict(family_pp),
        "high7_combined_pp": high7_combined_pp,
        "family_shares": family_shares,
        "wild_cadence": wild_cadence,
        "margs": margs,
        "cv": prof["cv"],
        "p_r_ge_1000_per_spin": p_r_ge_1000_per_spin,
        "p_r_ge_200_per_spin": p_r_ge_200_per_spin,
    }


# ----------------------------------------------------------------------
# Independent ≥30× share compute — both views: combo-final AND payid-anchored
# ----------------------------------------------------------------------

def compute_ge_30_share_independent(margs, base_rtp_pct):
    """Independent combo enumeration to compute ≥30× share both ways.

    Combo view: bucket each combo by its FINAL multiplier (post-wild-boost).
    Payid view: bucket per pay_id by nominal headline mult.
    """
    import itertools
    symbols_per_reel = [list(m.keys()) for m in margs]
    combo_tier_pp = defaultdict(float)
    pid_rtp_pp = defaultdict(float)
    pid_hits = defaultdict(float)
    for combo in itertools.product(*symbols_per_reel):
        prob = 1.0
        for marg, sym in zip(margs, combo):
            prob *= marg[sym]
        if prob == 0:
            continue
        result = EV.evaluate_payline(list(combo))
        if result is None:
            continue
        mult = float(result.multiplier)
        rtp_contrib = prob * mult * 100.0
        pid_rtp_pp[str(result.pay_id)] += rtp_contrib
        pid_hits[str(result.pay_id)] += prob
        if mult <= 1:
            combo_tier_pp["1x_le1"] += rtp_contrib
        elif mult < 5:
            combo_tier_pp["ge2_lt5"] += rtp_contrib
        elif mult < 10:
            combo_tier_pp["ge5_lt10"] += rtp_contrib
        elif mult < 20:
            combo_tier_pp["ge10_lt20"] += rtp_contrib
        elif mult < 30:
            combo_tier_pp["ge20_lt30"] += rtp_contrib
        elif mult < 50:
            combo_tier_pp["ge30_lt50"] += rtp_contrib
        elif mult < 100:
            combo_tier_pp["ge50_lt100"] += rtp_contrib
        elif mult < 200:
            combo_tier_pp["ge100_lt200"] += rtp_contrib
        elif mult < 500:
            combo_tier_pp["ge200_lt500"] += rtp_contrib
        else:
            combo_tier_pp["ge500"] += rtp_contrib

    ge_30_combo_pp = (combo_tier_pp.get("ge30_lt50", 0)
                      + combo_tier_pp.get("ge50_lt100", 0)
                      + combo_tier_pp.get("ge100_lt200", 0)
                      + combo_tier_pp.get("ge200_lt500", 0)
                      + combo_tier_pp.get("ge500", 0))
    base_total = sum(combo_tier_pp.values())
    ge_30_combo_share = (ge_30_combo_pp / base_total * 100) if base_total > 0 else 0.0

    # Payid-anchored (X's convention):
    # ≥30× = pay 21 (h7_pure 30×) + pay 2 (h7+w 30/60/120) + pay 3 (bar3 20/40/80) +
    #        pay 5 (bar2 10/20/40) + pay 1 (wild_pure 200×)
    # <30× = pay 9 (cherry1 1×) + pay 71 (cherry2 5×) + pay 4 (cherry3 15×) +
    #        pay 8 (bar_mixed 2/4×) + pay 7 (bar1 5/10/20×)
    ge_30_payid_pp = (pid_rtp_pp.get("21", 0) + pid_rtp_pp.get("2", 0)
                      + pid_rtp_pp.get("3", 0) + pid_rtp_pp.get("5", 0)
                      + pid_rtp_pp.get("1", 0))
    ge_30_payid_share = (ge_30_payid_pp / base_total * 100) if base_total > 0 else 0.0

    return {
        "combo_tier_pp": dict(combo_tier_pp),
        "pid_rtp_pp": dict(pid_rtp_pp),
        "pid_hits": dict(pid_hits),
        "base_total_pp": base_total,
        "ge_30_combo_pp": ge_30_combo_pp,
        "ge_30_combo_share_pct": ge_30_combo_share,
        "ge_30_payid_pp": ge_30_payid_pp,
        "ge_30_payid_share_pct": ge_30_payid_share,
    }


# ----------------------------------------------------------------------
# Cross-mode invariant manual checks (17 invariants — list per D's table)
# ----------------------------------------------------------------------

def check_17_invariants(r5, r2, r1):
    """All 17 cross-mode invariants per design_v14d §7."""
    out = []
    # 1. USER-RTP m5 in [491.5, 508.5]
    ok = 491.5 <= r5["total_rtp"] <= 508.5
    out.append(("01 USER-RTP", "[491.5, 508.5]",
                f"{r5['total_rtp']:.3f}pp", ok))
    # 2. CROSS-RTP m5 band [490, 510]
    ok = 490.0 <= r5["total_rtp"] <= 510.0
    out.append(("02 CROSS-RTP band", "[490, 510]",
                f"{r5['total_rtp']:.3f}pp", ok))
    # 3. CROSS-RTP m5 > m2
    ok = r5["total_rtp"] > r2["total_rtp"]
    out.append(("03 CROSS-RTP m5>m2", "m5 > m2",
                f"{r5['total_rtp']:.3f} > {r2['total_rtp']:.3f}", ok))
    # 4. HIT m5 band [0.30, 0.35]
    ok = 30.0 <= r5["base_hit"] <= 35.0
    out.append(("04 HIT band", "[0.30, 0.35]",
                f"{r5['base_hit']:.4f}%", ok))
    # 5. LUCKY-MONO m5 hit >= m2 + 0.05pp margin (D's TIGHT cell)
    margin_floor_hit = 0.05
    diff_hit = r5["base_hit"] - r2["base_hit"]
    ok = diff_hit >= margin_floor_hit
    out.append(("05 LUCKY-MONO hit margin", "m5 hit >= m2 + 0.05pp",
                f"diff={diff_hit:+.4f}pp (m5={r5['base_hit']:.4f}% m2={r2['base_hit']:.4f}%)", ok))
    # 6. LUCKY-MONO m5 trigger >= m2 + 1e-4 margin (D's TIGHT cell)
    margin_floor_trig_pp = 1e-4 * 100  # 0.01pp
    diff_trig_pp = (r5["trigger_frac"] - r2["trigger_frac"]) * 100
    ok = diff_trig_pp >= margin_floor_trig_pp - 1e-12
    out.append(("06 LUCKY-MONO trig margin", "m5 trig >= m2 + 1e-4",
                f"diff={diff_trig_pp:+.4f}pp (m5={r5['trigger']:.4f}% m2={r2['trigger']:.4f}%)", ok))
    # 7. TOP-JACKPOT-CADENCE m5/m2 >= 1.1
    m2_p1 = r2["pay_hits"].get("1", 1e-18)
    m5_p1 = r5["pay_hits"].get("1", 0)
    ratio = m5_p1 / m2_p1
    ok = ratio >= 1.1
    out.append(("07 TOP-JACKPOT-CADENCE", "m5/m2 >= 1.1",
                f"ratio={ratio:.4f}", ok))
    # 8. BAR-HIERARCHY §1 tied-tol 0.10pp
    b1 = r5["pay_hits"].get("7", 0)
    b2 = r5["pay_hits"].get("5", 0)
    b3 = r5["pay_hits"].get("3", 0)
    tied_tol = 0.001  # 0.10pp
    ok = (b1 >= b2 - tied_tol) and (b2 >= b3 - tied_tol)
    out.append(("08 BAR-HIERARCHY-§1", "P(b1)>=P(b2)>=P(b3) tied-tol 0.10pp",
                f"b1={b1*100:.4f}% b2={b2*100:.4f}% b3={b3*100:.4f}% "
                f"b1-b2={(b1-b2)*100:+.4f}pp b2-b3={(b2-b3)*100:+.4f}pp", ok))
    # 9. CHERRY-HIERARCHY c1 >= c2 >= c3
    c1 = r5["pay_hits"].get("9", 0)
    c2 = r5["pay_hits"].get("71", 0)
    c3 = r5["pay_hits"].get("4", 0)
    ok = (c1 >= c2 - tied_tol) and (c2 >= c3 - tied_tol)
    out.append(("09 CHERRY-HIERARCHY", "c1 >= c2 >= c3",
                f"c1={c1*100:.4f}% c2={c2*100:.4f}% c3={c3*100:.4f}%", ok))
    # 10. H7-HIERARCHY h7_wild >= h7_pure - 0.10pp
    h7w = r5["pay_hits"].get("2", 0)
    h7p = r5["pay_hits"].get("21", 0)
    ok = h7w >= h7p - tied_tol
    out.append(("10 H7-HIERARCHY", "h7_wild >= h7_pure - 0.10pp",
                f"h7w={h7w*100:.4f}% h7p={h7p*100:.4f}% diff={(h7w-h7p)*100:+.4f}pp", ok))
    # 11. P(R>=1000)/spin <= 1e-5
    ok = r5["p_r_ge_1000_per_spin"] <= 1e-5
    out.append(("11 1000+", "<= 1e-5",
                f"{r5['p_r_ge_1000_per_spin']:.3e}", ok))
    # 12. JACKPOT-VIS all reels jp <= 0.6%
    jps = [r5["margs"][i].get("jackpot", 0) * 100 for i in range(3)]
    ok = all(j <= 0.6 for j in jps)
    out.append(("12 JACKPOT-VIS", "all reels jp <= 0.6%",
                f"R1={jps[0]:.4f} R2={jps[1]:.4f} R3={jps[2]:.4f}", ok))
    # 13. REEL-ASYM-LUCKY R1 blank >= R3 blank
    ok = r5["r1_blank"] >= r5["r3_blank"]
    out.append(("13 REEL-ASYM-LUCKY", "R1 blank >= R3 blank",
                f"R1={r5['r1_blank']:.3f}% R3={r5['r3_blank']:.3f}%", ok))
    # 14. TOP-JACKPOT-ESC P(R>=200)/spin m5 > m2
    ok = r5["p_r_ge_200_per_spin"] > r2["p_r_ge_200_per_spin"]
    out.append(("14 TOP-JACKPOT-ESC", "P(R>=200)/spin m5 > m2",
                f"m5={r5['p_r_ge_200_per_spin']:.3e} m2={r2['p_r_ge_200_per_spin']:.3e}", ok))
    # 15. H7-NOT-CUT high7 marg ≥ M2_LC per reel
    h7_kept = []
    for ri in range(3):
        h5 = r5["margs"][ri].get("high7", 0) * 100
        h2 = M2_MARGS[ri].get("high7", 0) * 100
        h7_kept.append((ri + 1, h5, h2, h5 >= h2 - 1e-6))
    ok = all(item[3] for item in h7_kept)
    out.append(("15 H7-NOT-CUT", "high7 marg >= M2_LC per reel",
                "; ".join(f"R{r}: {a:.3f}>={b:.3f}" for r, a, b, _ in h7_kept), ok))
    # 16. FAM-SHARE bar3 [5, 22]
    b3_sh = r5["family_shares"].get("bar3", 0)
    ok = 5.0 <= b3_sh <= 22.0
    out.append(("16 FAM-SHARE b3", "[5, 22]",
                f"{b3_sh:.2f}%", ok))
    # 17. FAM-SHARE wild informational
    w_sh = r5["family_shares"].get("wild_pure", 0)
    out.append(("17 FAM-SHARE wld (info)", "informational",
                f"{w_sh:.3f}%", True))
    return out


def jackpot_check(r):
    out = []
    for ri in range(3):
        jp = r["margs"][ri].get("jackpot", 0) * 100
        ok = jp <= 0.6
        out.append((f"JACKPOT-VIS R{ri+1}", "jp marginal",
                    f"{jp:.4f}%", "≤ 0.6%", ok))
    return out


# ----------------------------------------------------------------------
# D's claims for diff
# ----------------------------------------------------------------------

D_CLAIM = {
    "total_rtp": 508.21,
    "base_rtp": 98.68,
    "feature_rtp": 409.53,
    "base_hit": 33.91,
    "trigger": 3.3205,
    "r1_blank": 28.37,
    "r3_blank": 24.61,
    "wild_cadence_1in": 60993,
    "ge_30_share_payid_pct": 40.12,
    "ge_30_share_combo_pct": 23.81,
    "pay_hits_pct": {
        "9": 17.4369, "71": 1.2384, "4": 0.0291,
        "1": 0.0016, "2": 0.1461, "21": 0.1990,
        "3": 0.2481, "5": 1.0839, "7": 1.1140, "8": 12.4137,
    },
    "family_shares_pct": {
        "cherry1": 17.67, "cherry2": 6.27, "cherry3": 0.44,
        "bar1": 7.77, "bar2": 15.15, "bar3": 8.21,
        "bar_mixed": 27.73, "high7": 16.43, "wild_pure": 0.33,
    },
    "p_r_ge_1000_per_spin": 1.10e-7,
    "p_r_ge_200_per_spin": 3.91e-3,
}


def diff_vs_d(r):
    diffs = []
    diffs.append(("total_rtp", r["total_rtp"], D_CLAIM["total_rtp"],
                  abs(r["total_rtp"] - D_CLAIM["total_rtp"])))
    diffs.append(("base_rtp", r["base_rtp"], D_CLAIM["base_rtp"],
                  abs(r["base_rtp"] - D_CLAIM["base_rtp"])))
    diffs.append(("feature_rtp", r["feature_rtp"], D_CLAIM["feature_rtp"],
                  abs(r["feature_rtp"] - D_CLAIM["feature_rtp"])))
    diffs.append(("base_hit", r["base_hit"], D_CLAIM["base_hit"],
                  abs(r["base_hit"] - D_CLAIM["base_hit"])))
    diffs.append(("trigger", r["trigger"], D_CLAIM["trigger"],
                  abs(r["trigger"] - D_CLAIM["trigger"])))
    diffs.append(("r1_blank", r["r1_blank"], D_CLAIM["r1_blank"],
                  abs(r["r1_blank"] - D_CLAIM["r1_blank"])))
    diffs.append(("r3_blank", r["r3_blank"], D_CLAIM["r3_blank"],
                  abs(r["r3_blank"] - D_CLAIM["r3_blank"])))
    diffs.append(("wild_cadence", r["wild_cadence"], D_CLAIM["wild_cadence_1in"],
                  abs(r["wild_cadence"] - D_CLAIM["wild_cadence_1in"])))
    for pid, claim_hit in D_CLAIM["pay_hits_pct"].items():
        my = r["pay_hits"].get(pid, 0) * 100
        diffs.append((f"pay_hit[{pid}]", my, claim_hit, abs(my - claim_hit)))
    for fam, claim_share in D_CLAIM["family_shares_pct"].items():
        my = r["family_shares"].get(fam, 0)
        diffs.append((f"family_share[{fam}]", my, claim_share, abs(my - claim_share)))
    return diffs


# ----------------------------------------------------------------------
# Write temp weights for verify.py
# ----------------------------------------------------------------------

def write_temp_weights(mode, weights, *, feature_params):
    tmp_dir = TMP_ROOT / f"mode_{mode}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "machine": "M15",
        "mode": mode,
        "reel_set": "default",
        "weights": weights,
        "feature_params": feature_params,
        "_notes": [
            f"V verifier v14d temp output — DO NOT SHIP. Mode {mode}.",
            "Generated from per-family scalar over M2_LC anchor (V-side, independent of D's script)",
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": ["doublediamond", "high7", "topdollar"],
        },
    }
    out_path = tmp_dir / "weights.json"
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out_path


def copy_production_weights_to_tmp(mode, src_path):
    """Copy production weights byte-for-byte into temp dir for modes 1/2/7."""
    tmp_dir = TMP_ROOT / f"mode_{mode}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "weights.json"
    out_path.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def run_verify_against_tmp():
    cmd = [
        sys.executable,
        "-m", "slot_designer.machines.M15.verify",
        "--weights-dir", str(TMP_ROOT),
    ]
    result = subprocess.run(cmd, cwd=str(_ROOT),
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_verify_reds(stdout):
    reds = []
    current_mode = None
    for line in stdout.splitlines():
        if "[FAIL]" in line:
            reds.append(line.strip())
    return reds


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print("=" * 70)
    print("M15 v14d INDEPENDENT VERIFIER — Mode 5 (M5_HMV_plus)")
    print("=" * 70)

    # ----- 1. Analytic + engine numerics per mode
    results = {}
    weights_by_mode = {}
    margs_by_mode = {1: M1_MARGS, 7: M7_MARGS, 2: M2_MARGS, 5: M5_MARGS}
    for mode in (1, 7, 2, 5):
        analytic = evaluate(margs_by_mode[mode], mode, tag="analytic")
        w_raw = marginals_to_weights(STRIPS, margs_by_mode[mode])
        w_b = apply_mechanism_b_blanks(STRIPS, w_raw)
        engine_margs = reel_marginals_from_weights(STRIPS, w_b)
        engine_r = evaluate(engine_margs, mode, tag="engine")
        results[mode] = {"analytic": analytic, "engine": engine_r}
        weights_by_mode[mode] = w_b

    # ----- 1b. Mode 5 marginal table reconstruction
    print("\n--- Mode 5 marginals (V-reconstructed from scalar) ---")
    print(f"  c_lift={C_LIFT} b1_lift={B1_LIFT} b2_lift={B2_LIFT} "
          f"b3_lift={B3_LIFT} h_lift={H_LIFT[0]} dd_lift={DD_LIFT[0]} td_lift={TD_LIFT}")
    for ri in range(3):
        print(f"  R{ri+1}: " + ", ".join(
            f"{k}={v*100:.4f}%" for k, v in sorted(M5_MARGS[ri].items())))

    # ----- 2. Print analytic per mode
    for mode in (1, 7, 2, 5):
        print(f"\n--- MODE {mode} ANALYTIC ---")
        r = results[mode]["analytic"]
        for k in ("total_rtp", "base_rtp", "feature_rtp", "hit_session",
                  "base_hit", "trigger", "r1_blank", "r2_blank", "r3_blank",
                  "wild_cadence", "cv"):
            v = r[k]
            if k == "wild_cadence":
                print(f"  {k}: 1/{v:.0f}")
            else:
                print(f"  {k}: {v:.5f}")
        print(f"  P(R>=1000/spin): {r['p_r_ge_1000_per_spin']:.3e}")
        print(f"  P(R>=200/spin):  {r['p_r_ge_200_per_spin']:.3e}")

        print(f"\n--- MODE {mode} ENGINE (post integer + mech B) ---")
        r = results[mode]["engine"]
        for k in ("total_rtp", "base_rtp", "feature_rtp", "hit_session",
                  "base_hit", "trigger", "r1_blank", "r2_blank", "r3_blank",
                  "wild_cadence"):
            v = r[k]
            if k == "wild_cadence":
                print(f"  {k}: 1/{v:.0f}")
            else:
                print(f"  {k}: {v:.5f}")

    # ----- 3. Per-pay-id mode 5
    print(f"\n--- MODE 5 PER-PAY-ID (analytic) ---")
    r = results[5]["analytic"]
    pid_order = ["9", "71", "4", "1", "2", "21", "3", "5", "7", "8"]
    print(f"  {'pid':>4} {'fam':<12} {'mult':>5} {'hit%':>10} {'1in':>10} {'rtp_pp':>8}")
    for pid in pid_order:
        fam = FAMILY_OF_PAY_ID.get(pid, "?")
        mult = PAY_MULT.get(pid, 0)
        p = r["pay_hits"].get(pid, 0) * 100
        oneinn = (1 / (p / 100)) if p > 0 else float("inf")
        rtp_pp = r["pay_rtp"].get(pid, 0) * 100
        print(f"  {pid:>4} {fam:<12} {mult:>5} {p:>9.4f}% {oneinn:>10.0f} "
              f"{rtp_pp:>7.4f}")

    # ----- 4. 17 cross-mode invariants check (analytic + engine)
    r1 = results[1]["analytic"]
    r2 = results[2]["analytic"]
    r5 = results[5]["analytic"]
    e5 = results[5]["engine"]
    e2 = results[2]["engine"]
    e1 = results[1]["engine"]

    print("\n\n========================================")
    print("17 CROSS-MODE INVARIANTS (analytic)")
    print("========================================")
    inv_checks_a = check_17_invariants(r5, r2, r1)
    n_pass_a = 0
    for cat, expected, val, ok in inv_checks_a:
        st = "PASS" if ok else "FAIL"
        if ok:
            n_pass_a += 1
        print(f"  [{st}] {cat:30}  {expected:35}  {val}")
    print(f"\nAnalytic: {n_pass_a}/{len(inv_checks_a)} pass")

    print("\n\n========================================")
    print("17 CROSS-MODE INVARIANTS (ENGINE-realized, post mech B)")
    print("========================================")
    inv_checks_e = check_17_invariants(e5, e2, e1)
    n_pass_e = 0
    for cat, expected, val, ok in inv_checks_e:
        st = "PASS" if ok else "FAIL"
        if ok:
            n_pass_e += 1
        print(f"  [{st}] {cat:30}  {expected:35}  {val}")
    print(f"\nEngine: {n_pass_e}/{len(inv_checks_e)} pass")

    # ----- 5. SPECIAL FOCUS: TIGHT margins
    print("\n\n========================================")
    print("SPECIAL FOCUS: m5 LUCKY-MONO TIGHT MARGINS")
    print("========================================")
    print(f"\nm5 HIT vs m2 HIT (analytic):  m5={r5['base_hit']:.6f}%  m2={r2['base_hit']:.6f}%  diff={r5['base_hit']-r2['base_hit']:+.6f}pp")
    print(f"m5 HIT vs m2 HIT (engine):    m5={e5['base_hit']:.6f}%  m2={e2['base_hit']:.6f}%  diff={e5['base_hit']-e2['base_hit']:+.6f}pp")
    margin_hit_analytic = r5["base_hit"] - r2["base_hit"]
    margin_hit_engine = e5["base_hit"] - e2["base_hit"]
    print(f"  D claimed +0.06pp margin (analytic).")
    print(f"  V analytic: {margin_hit_analytic:+.4f}pp. SURVIVES verify.py (>= 0 strict)? "
          f"{'YES' if margin_hit_engine >= -1e-9 else 'NO'}")
    print(f"  V engine:   {margin_hit_engine:+.4f}pp.")

    print(f"\nm5 TRIG vs m2 TRIG (analytic):  m5={r5['trigger']:.6f}%  m2={r2['trigger']:.6f}%  diff={(r5['trigger_frac']-r2['trigger_frac'])*100:+.6f}pp")
    print(f"m5 TRIG vs m2 TRIG (engine):    m5={e5['trigger']:.6f}%  m2={e2['trigger']:.6f}%  diff={(e5['trigger_frac']-e2['trigger_frac'])*100:+.6f}pp")
    margin_trig_analytic = (r5["trigger_frac"] - r2["trigger_frac"]) * 100
    margin_trig_engine = (e5["trigger_frac"] - e2["trigger_frac"]) * 100
    print(f"  D claimed +0.0165pp margin (analytic).")
    print(f"  V analytic: {margin_trig_analytic:+.6f}pp.")
    print(f"  V engine:   {margin_trig_engine:+.6f}pp. SURVIVES verify.py (>= 0 strict)? "
          f"{'YES' if margin_trig_engine >= -1e-9 else 'NO'}")

    # Bar §1 explicit
    print(f"\n--- Bar §1 hierarchy (m5 engine) ---")
    b1 = e5["pay_hits"].get("7", 0) * 100
    b2 = e5["pay_hits"].get("5", 0) * 100
    b3 = e5["pay_hits"].get("3", 0) * 100
    print(f"  P(bar1_pure) = {b1:.5f}%")
    print(f"  P(bar2_pure) = {b2:.5f}%")
    print(f"  P(bar3_pure) = {b3:.5f}%")
    print(f"  b1 - b2 = {b1-b2:+.5f}pp ({'STRICT >' if b1 > b2 + 1e-6 else 'TIED'})")
    print(f"  b2 - b3 = {b2-b3:+.5f}pp ({'STRICT >' if b2 > b3 + 1e-6 else 'TIED'})")
    tied_tol_pp = 0.10  # 0.10pp
    bar_pass_tied_tol = (b1 >= b2 - tied_tol_pp) and (b2 >= b3 - tied_tol_pp)
    print(f"  PASS within verify.py 0.10pp tied-tol? {'YES' if bar_pass_tied_tol else 'NO'}")
    strict = b1 > b2 and b2 > b3
    print(f"  STRICT > ? {'YES' if strict else 'NO (TIED within tol)'}")

    # ----- 6. INDEPENDENT ≥30× share compute
    print("\n\n========================================")
    print("INDEPENDENT ≥30× MULT SHARE COMPUTE")
    print("========================================")
    for mode, label in ((2, "M2_LC anchor"), (5, "M5_HMV_plus (V)")):
        r = results[mode]["analytic"]
        decomp = compute_ge_30_share_independent(r["margs"], r["base_rtp"])
        print(f"\n--- Mode {mode} ({label}) ---")
        print(f"  Base RTP (combo enum): {decomp['base_total_pp']:.4f}pp  "
              f"(eval profile: {r['base_rtp']:.4f}pp)")
        print(f"  Combo tier breakdown:")
        for tier in ("1x_le1", "ge2_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt30",
                     "ge30_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500", "ge500"):
            v = decomp["combo_tier_pp"].get(tier, 0)
            print(f"    {tier:14s} = {v:7.4f}pp")
        print(f"  ≥30× share (COMBO): {decomp['ge_30_combo_share_pct']:.2f}%  "
              f"(ge30_pp={decomp['ge_30_combo_pp']:.3f}pp)")
        print(f"  ≥30× share (PAYID): {decomp['ge_30_payid_share_pct']:.2f}%  "
              f"(ge30_pp={decomp['ge_30_payid_pp']:.3f}pp)")
        print(f"    pid breakdown: " + ", ".join(
            f"{pid}={decomp['pid_rtp_pp'].get(pid, 0):.3f}pp"
            for pid in pid_order))
        if mode == 5:
            print(f"\n  D's claim (payid): {D_CLAIM['ge_30_share_payid_pct']:.2f}%")
            print(f"  D's claim (combo): {D_CLAIM['ge_30_share_combo_pct']:.2f}%")
            print(f"  V vs D delta (payid): {decomp['ge_30_payid_share_pct'] - D_CLAIM['ge_30_share_payid_pct']:+.4f}pp")
            print(f"  V vs D delta (combo): {decomp['ge_30_combo_share_pct'] - D_CLAIM['ge_30_share_combo_pct']:+.4f}pp")

    # ----- 7. Diff vs D's claims
    print("\n\n========================================")
    print("DIFF vs D's claims (analytic)")
    print("========================================")
    diffs = diff_vs_d(r5)
    large = []
    for name, my, dv, delta in diffs:
        if name == "wild_cadence":
            ok = delta <= max(2000, abs(dv) * 0.05)
        elif "pay_hit" in name or "family_share" in name:
            ok = delta <= max(0.5, abs(dv) * 0.02)
        else:
            ok = delta <= 0.5
        flag = "OK" if ok else "DIFF"
        if not ok:
            large.append((name, my, dv, delta))
        print(f"  {flag:4}  {name:<24}  mine={my:>12.4f}  D={dv:>12.4f}  delta={delta:>10.4f}")
    if large:
        print(f"\nTop diffs vs D:")
        for name, mine, dv, delta in sorted(large, key=lambda x: -x[3])[:5]:
            print(f"  {name}: mine={mine:.4f} D={dv:.4f} delta={delta:.4f}")

    # ----- 8. Write temp weights for verify.py
    print("\n\n========================================")
    print("WRITE TEMP WEIGHTS (engine = post mech B integer)")
    print("========================================")
    # Mode 1/2/7: copy production weights byte-for-byte (per task spec)
    for mode, src in ((1, W_M1), (2, W_M2), (7, W_M7)):
        p = copy_production_weights_to_tmp(mode, src)
        print(f"  mode {mode}: {p} (production copy)")
    # Mode 5: write V-reconstructed weights
    w = weights_by_mode[5]
    fp = FP_BY_MODE[5]
    p5 = write_temp_weights(5, w, feature_params=fp)
    print(f"  mode 5: {p5} (V-derived from scalar over M2_LC)")

    # ----- 9. Run verify.py
    print("\n\n========================================")
    print("RUN verify.py against temp weights")
    print("========================================")
    rc, stdout, stderr = run_verify_against_tmp()
    print(f"\nexit_code: {rc}")
    if stderr.strip():
        print(f"\nSTDERR (truncated):")
        for line in stderr.splitlines()[:40]:
            print(f"  {line}")
    log_path = TMP_ROOT / "verify_output.txt"
    log_path.write_text(stdout, encoding="utf-8")
    print(f"\nFull verify.py output written: {log_path}")

    reds = parse_verify_reds(stdout)
    print(f"\n{len(reds)} RED line(s):")
    for line in reds:
        print(f"  {line}")

    # Classify REDs by mode
    reds_by_mode = defaultdict(list)
    for line in reds:
        # line looks like "[FAIL] CAT  m5 ..."
        if "m5" in line or "mode 5" in line:
            reds_by_mode["m5"].append(line)
        elif "m2" in line or "mode 2" in line:
            reds_by_mode["m2"].append(line)
        elif "m1" in line or "mode 1" in line:
            reds_by_mode["m1"].append(line)
        elif "m7" in line or "mode 7" in line:
            reds_by_mode["m7"].append(line)
        else:
            reds_by_mode["cross"].append(line)
    print(f"\nMode 5 REDs ({len(reds_by_mode['m5'])}):")
    for line in reds_by_mode["m5"]:
        print(f"  {line}")
    print(f"\nMode 1 REDs ({len(reds_by_mode['m1'])}):")
    for line in reds_by_mode["m1"]:
        print(f"  {line}")
    print(f"\nMode 2 REDs ({len(reds_by_mode['m2'])}):")
    for line in reds_by_mode["m2"]:
        print(f"  {line}")
    print(f"\nMode 7 REDs ({len(reds_by_mode['m7'])}):")
    for line in reds_by_mode["m7"]:
        print(f"  {line}")
    print(f"\nCross-mode REDs ({len(reds_by_mode['cross'])}):")
    for line in reds_by_mode["cross"]:
        print(f"  {line}")

    # ----- 10. Final summary
    print("\n\n========================================")
    print("V14d MODE 5 FINAL SUMMARY")
    print("========================================")
    print(f"\nAnalytic 17 invariants pass: {n_pass_a}/{len(inv_checks_a)}")
    print(f"Engine 17 invariants pass:   {n_pass_e}/{len(inv_checks_e)}")
    print(f"\nverify.py exit_code: {rc}")
    print(f"verify.py total RED: {len(reds)}")
    print(f"  mode 5 REDs: {len(reds_by_mode['m5'])}")
    print(f"  mode 1 REDs: {len(reds_by_mode['m1'])}")
    print(f"  mode 2 REDs: {len(reds_by_mode['m2'])}")
    print(f"  mode 7 REDs: {len(reds_by_mode['m7'])}")
    print(f"  cross-mode REDs: {len(reds_by_mode['cross'])}")

    print("\n--- Analytic vs engine drift per mode ---")
    for mode in (1, 7, 2, 5):
        a = results[mode]["analytic"]
        e = results[mode]["engine"]
        print(f"  mode {mode}: RTP {a['total_rtp']:.3f} -> {e['total_rtp']:.3f} (drift {e['total_rtp']-a['total_rtp']:+.3f}pp)  "
              f"hit {a['base_hit']:.4f} -> {e['base_hit']:.4f} (drift {e['base_hit']-a['base_hit']:+.4f}pp)  "
              f"trig {a['trigger']:.4f} -> {e['trigger']:.4f} (drift {e['trigger']-a['trigger']:+.4f}pp)")

    # ----- 11. RTP margin to 490/510 band
    print(f"\n--- RTP margin analysis (engine) ---")
    print(f"  Engine m5 RTP: {e5['total_rtp']:.3f}pp")
    print(f"  Margin to 490 floor: {e5['total_rtp']-490.0:+.3f}pp")
    print(f"  Margin to 510 ceiling: {510.0-e5['total_rtp']:+.3f}pp")
    print(f"  Margin to 508.5 user-target ceiling: {508.5-e5['total_rtp']:+.3f}pp")

    return {
        "results": results,
        "analytic_checks": inv_checks_a,
        "engine_checks": inv_checks_e,
        "verify_rc": rc,
        "verify_reds": reds,
        "reds_by_mode": dict(reds_by_mode),
        "weights": weights_by_mode,
    }


if __name__ == "__main__":
    main()
