"""M15 v14b modes 7/2/5 — INDEPENDENT VERIFIER (2026-05-12).

Verifies D's M7_F110, M2_Q_h7_max_uneven_dd, M5_H_from_M2_Q candidates from
m15_v14b_design_modes_725.py WITHOUT importing anything from D's script.
Takes each mode's marginals as **direct numeric input** from D's design doc
(`design_v14b_modes_725.md` §2.2, §3.2, §4.2), recomputes integer per-stop
weights via local primitives, runs analytic_profile_from_marginals, and
exercises verify.py against the resulting temp weights.

Outputs:
  * Recomputed metrics for each of m7 / m2 / m5: total RTP, base RTP, feature
    RTP, hit, R1 blank, wild cadence, per-pay frequencies, family shares
  * Cross-mode invariant manual checks (MODE7-BIGPAY/CUT/TRIGGER,
    LUCKY-MONO, CROSS-RTP)
  * verify.py RED classification per mode
  * Numeric diff vs D's claims

DOES NOT modify production files. Writes temp weights to
`session_artifacts/M15/_tmp_v14b_verify/mode_{1,2,5,7}/weights.json`.
"""
from __future__ import annotations

import hashlib
import json
import os
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
from slot_designer.core.devtools.player_experience import symbol_window_probability
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution

_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
W_M1 = _M15_DIR / "weights" / "mode_1" / "weights.json"
W_M2 = _M15_DIR / "weights" / "mode_2" / "weights.json"
W_M5 = _M15_DIR / "weights" / "mode_5" / "weights.json"
W_M7 = _M15_DIR / "weights" / "mode_7" / "weights.json"

TMP_ROOT = _ROOT / "session_artifacts" / "M15" / "_tmp_v14b_verify"

# ----------------------------------------------------------------------
# D's CANDIDATES — taken DIRECTLY from design_v14b_modes_725.md tables.
# DO NOT import from D's script.
# ----------------------------------------------------------------------

# Mode 1 baseline (shipped C38_C14) — for cross-mode comparison only.
M1_R1 = {"blank": 0.385,  "cherry": 0.040, "1bar": 0.202, "2bar": 0.165,
         "3bar": 0.103,  "high7": 0.072, "doublediamond": 0.029,
         "jackpot": 0.004}
M1_R2 = {"blank": 0.503,  "cherry": 0.035, "1bar": 0.165, "2bar": 0.135,
         "3bar": 0.073,  "high7": 0.057, "doublediamond": 0.028,
         "jackpot": 0.004}
M1_R3 = {"blank": 0.5897, "cherry": 0.025, "1bar": 0.135, "2bar": 0.110,
         "3bar": 0.055,  "high7": 0.047, "doublediamond": 0.024,
         "topdollar": 0.0113, "jackpot": 0.003}

# Mode 7 M7_F110 — design_v14b §2.2 (K-scaled from m1 with F=1.10 blank lift).
# IMPORTANT: per design doc 2.2 table values are in PERCENT. R1 blank 42.35%,
# cherry 3.70%, etc.
M7_R1 = {"blank": 0.4235, "cherry": 0.0370, "1bar": 0.1868, "2bar": 0.1525,
         "3bar": 0.0952, "high7": 0.0720, "doublediamond": 0.0290,
         "jackpot": 0.0040}
M7_R2 = {"blank": 0.5533, "cherry": 0.0307, "1bar": 0.1447, "2bar": 0.1184,
         "3bar": 0.0640, "high7": 0.0570, "doublediamond": 0.0280,
         "jackpot": 0.0040}
M7_R3 = {"blank": 0.6487, "cherry": 0.0205, "1bar": 0.1105, "2bar": 0.0900,
         "3bar": 0.0450, "high7": 0.0470, "doublediamond": 0.0240,
         "topdollar": 0.0113, "jackpot": 0.0030}

# Mode 2 M2_Q_h7_max_uneven_dd — design_v14b §3.2.
# R1 blank 16.10%, cherry 9.0%, 1bar 14.0%, 2bar 25.0%, 3bar 15.0%, h7 15.0%,
# dd 5.5%, jp 0.40%. R2 27.60% blank, R3 40.70% blank (with topdollar 3.0%).
M2_R1 = {"blank": 0.1610, "cherry": 0.0900, "1bar": 0.1400, "2bar": 0.2500,
         "3bar": 0.1500, "high7": 0.1500, "doublediamond": 0.0550,
         "jackpot": 0.0040}
M2_R2 = {"blank": 0.2760, "cherry": 0.0800, "1bar": 0.1400, "2bar": 0.2200,
         "3bar": 0.1000, "high7": 0.1300, "doublediamond": 0.0500,
         "jackpot": 0.0040}
M2_R3 = {"blank": 0.4070, "cherry": 0.0600, "1bar": 0.1200, "2bar": 0.1800,
         "3bar": 0.0800, "high7": 0.1100, "doublediamond": 0.0100,
         "topdollar": 0.0300, "jackpot": 0.0030}

# Mode 5 M5_H_from_M2_Q — design_v14b §4.2 (M2_Q with dd+8%, td+3%, cherry+3%).
# After normalize (blank residual): R1 15.39%, R2 26.96%, R3 40.35%.
M5_R1 = {"blank": 0.1539, "cherry": 0.0927, "1bar": 0.1400, "2bar": 0.2500,
         "3bar": 0.1500, "high7": 0.1500, "doublediamond": 0.0594,
         "jackpot": 0.0040}
M5_R2 = {"blank": 0.2696, "cherry": 0.0824, "1bar": 0.1400, "2bar": 0.2200,
         "3bar": 0.1000, "high7": 0.1300, "doublediamond": 0.0540,
         "jackpot": 0.0040}
M5_R3 = {"blank": 0.4035, "cherry": 0.0618, "1bar": 0.1200, "2bar": 0.1800,
         "3bar": 0.0800, "high7": 0.1100, "doublediamond": 0.0108,
         "topdollar": 0.0309, "jackpot": 0.0030}


def normalize_margs(d):
    """Recompute blank as residual; sum to 1 exactly."""
    out = dict(d)
    # Sum non-blank
    nb = sum(v for k, v in out.items() if k != "blank")
    if nb > 1.0:
        # rescale (means doc rows already summed > 1: just normalize)
        s = sum(out.values())
        return {k: v / s for k, v in out.items() if v > 0}
    out["blank"] = max(0.0, 1.0 - nb)
    return out


M1_MARGS = [normalize_margs(M1_R1), normalize_margs(M1_R2), normalize_margs(M1_R3)]
M7_MARGS = [normalize_margs(M7_R1), normalize_margs(M7_R2), normalize_margs(M7_R3)]
M2_MARGS = [normalize_margs(M2_R1), normalize_margs(M2_R2), normalize_margs(M2_R3)]
M5_MARGS = [normalize_margs(M5_R1), normalize_margs(M5_R2), normalize_margs(M5_R3)]


# ----------------------------------------------------------------------
# Load engine + strips + per-mode feature_params (LOCKED v9)
# ----------------------------------------------------------------------

engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator
STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

# Feature params per mode (v9 locked)
FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(W_M2.read_text(encoding="utf-8"))["feature_params"],
    5: json.loads(W_M5.read_text(encoding="utf-8"))["feature_params"],
    7: json.loads(W_M7.read_text(encoding="utf-8"))["feature_params"],
}


def feature_ev_per_trigger(fp):
    """E[R] over the 4-round accept/reroll flow."""
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
# (byte-for-byte same primitives D uses; reimpl locally)
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
# Cross-mode invariant manual checks (independent of verify.py)
# ----------------------------------------------------------------------

def check_mode7_invariants(r7, r1):
    out = []
    # MODE7-CUT: pay 9, 71, 8, 7, 5, 3 freq m7 < m1
    for pid in ["9", "71", "8", "7", "5", "3"]:
        m1_p = r1["pay_hits"].get(pid, 0)
        m7_p = r7["pay_hits"].get(pid, 0)
        ok = m7_p < m1_p - 1e-12
        out.append(("MODE7-CUT", f"pay{pid} ({FAMILY_OF_PAY_ID.get(pid)})",
                    f"m7={m7_p*100:.4f}% m1={m1_p*100:.4f}%",
                    "m7 < m1", ok))
    # MODE7-BIGPAY: pay 1, 2, 21 m7/m1 ratio in [0.85, 1.15]
    for pid in ["1", "2", "21"]:
        m1_p = r1["pay_hits"].get(pid, 0)
        m7_p = r7["pay_hits"].get(pid, 0)
        ratio = m7_p / m1_p if m1_p > 0 else float("inf")
        ok = 0.85 <= ratio <= 1.15
        out.append(("MODE7-BIGPAY", f"pay{pid} ({FAMILY_OF_PAY_ID.get(pid)})",
                    f"ratio={ratio:.4f}",
                    "[0.85, 1.15]", ok))
    # MODE7-TRIGGER: diff ≤ 5e-4
    diff = abs(r7["trigger_frac"] - r1["trigger_frac"])
    ok = diff <= 5e-4
    out.append(("MODE7-TRIGGER", "diff",
                f"|m7_trig - m1_trig|={diff:.6f}",
                "≤ 5e-4", ok))
    # CROSS-RTP m7 band [83, 87]
    ok = 83.0 <= r7["total_rtp"] <= 87.0
    out.append(("CROSS-RTP m7 band", "RTP",
                f"{r7['total_rtp']:.3f}pp",
                "[83, 87]", ok))
    # CROSS-RTP m7 < m1
    ok = r7["total_rtp"] < r1["total_rtp"]
    out.append(("CROSS-RTP m7<m1", "ladder",
                f"m7={r7['total_rtp']:.2f} m1={r1['total_rtp']:.2f}",
                "m7 < m1", ok))
    # HIT m7 band [10, 16] (base hit per verify.py MODE_HIT_BAND)
    ok = 10.0 <= r7["base_hit"] <= 16.0
    out.append(("HIT m7 band", "base hit",
                f"{r7['base_hit']:.3f}%",
                "[10, 16]", ok))
    # LUCKY-MONO m7 < m1 hit
    ok = r7["base_hit"] < r1["base_hit"]
    out.append(("LUCKY-MONO m7<m1 hit", "hit",
                f"m7={r7['base_hit']:.2f} m1={r1['base_hit']:.2f}",
                "m7 < m1", ok))
    # 1000+ m7 ≤ 1e-5
    ok = r7["p_r_ge_1000_per_spin"] <= 1e-5
    out.append(("1000+ m7", "P(R>=1000/spin)",
                f"{r7['p_r_ge_1000_per_spin']:.3e}",
                "≤ 1e-5", ok))
    return out


def check_mode2_invariants(r2, r1):
    out = []
    # CROSS-RTP m2 [290, 310]
    ok = 290.0 <= r2["total_rtp"] <= 310.0
    out.append(("CROSS-RTP m2 band", "RTP",
                f"{r2['total_rtp']:.3f}pp",
                "[290, 310]", ok))
    # CROSS-RTP m2 > m1
    ok = r2["total_rtp"] > r1["total_rtp"]
    out.append(("CROSS-RTP m2>m1", "ladder",
                f"m2={r2['total_rtp']:.2f} m1={r1['total_rtp']:.2f}",
                "m2 > m1", ok))
    # HIT m2 band [30, 35]
    ok = 30.0 <= r2["base_hit"] <= 35.0
    out.append(("HIT m2 band", "base hit",
                f"{r2['base_hit']:.3f}%",
                "[30, 35]", ok))
    # LUCKY-MONO m2 > m1 hit
    ok = r2["base_hit"] > r1["base_hit"]
    out.append(("LUCKY-MONO m2>m1 hit", "hit",
                f"m2={r2['base_hit']:.2f} m1={r1['base_hit']:.2f}",
                "m2 > m1", ok))
    # LUCKY-MONO m2 trigger ≥ m1
    ok = r2["trigger_frac"] >= r1["trigger_frac"] - 1e-12
    out.append(("LUCKY-MONO m2>=m1 trig", "trigger",
                f"m2={r2['trigger']:.3f}% m1={r1['trigger']:.3f}%",
                "m2 ≥ m1", ok))
    # LUCKY-MONO bar2 peak: P(bar2) > P(bar1) AND P(bar2) > P(bar3)
    p_b1 = r2["pay_hits"].get("7", 0)
    p_b2 = r2["pay_hits"].get("5", 0)
    p_b3 = r2["pay_hits"].get("3", 0)
    ok = p_b2 > p_b1 and p_b2 > p_b3
    out.append(("LUCKY-MONO bar2 peak", "P(bar1/2/3)",
                f"b1={p_b1*100:.4f}% b2={p_b2*100:.4f}% b3={p_b3*100:.4f}%",
                "b2 > b1, b2 > b3", ok))
    # TOP-JACKPOT-ESC m2/m1 ≤ 1.5
    m1_p1 = r1["pay_hits"].get("1", 0)
    m2_p1 = r2["pay_hits"].get("1", 0)
    ratio = m2_p1 / m1_p1 if m1_p1 > 0 else float("inf")
    ok = ratio <= 1.5
    out.append(("TOP-JACKPOT-ESC m2/m1", "wild_pure ratio",
                f"ratio={ratio:.4f}",
                "≤ 1.5", ok))
    # 1000+ m2 ≤ 1e-5
    ok = r2["p_r_ge_1000_per_spin"] <= 1e-5
    out.append(("1000+ m2", "P(R>=1000/spin)",
                f"{r2['p_r_ge_1000_per_spin']:.3e}",
                "≤ 1e-5", ok))
    return out


def check_mode5_invariants(r5, r2, r1):
    out = []
    # CROSS-RTP m5 [480, 520]
    ok = 480.0 <= r5["total_rtp"] <= 520.0
    out.append(("CROSS-RTP m5 band", "RTP",
                f"{r5['total_rtp']:.3f}pp",
                "[480, 520]", ok))
    # CROSS-RTP m5 > m2
    ok = r5["total_rtp"] > r2["total_rtp"]
    out.append(("CROSS-RTP m5>m2", "ladder",
                f"m5={r5['total_rtp']:.2f} m2={r2['total_rtp']:.2f}",
                "m5 > m2", ok))
    # HIT m5 band [30, 35]
    ok = 30.0 <= r5["base_hit"] <= 35.0
    out.append(("HIT m5 band", "base hit",
                f"{r5['base_hit']:.3f}%",
                "[30, 35]", ok))
    # LUCKY-MONO m5 >= m2 hit
    ok = r5["base_hit"] >= r2["base_hit"] - 1e-9
    out.append(("LUCKY-MONO m5>=m2 hit", "hit",
                f"m5={r5['base_hit']:.4f}% m2={r2['base_hit']:.4f}%",
                "m5 ≥ m2", ok))
    # LUCKY-MONO m5 >= m2 trig
    ok = r5["trigger_frac"] >= r2["trigger_frac"] - 1e-9
    out.append(("LUCKY-MONO m5>=m2 trig", "trigger",
                f"m5={r5['trigger']:.4f}% m2={r2['trigger']:.4f}%",
                "m5 ≥ m2", ok))
    # LUCKY-MONO bar2 peak
    p_b1 = r5["pay_hits"].get("7", 0)
    p_b2 = r5["pay_hits"].get("5", 0)
    p_b3 = r5["pay_hits"].get("3", 0)
    ok = p_b2 > p_b1 and p_b2 > p_b3
    out.append(("LUCKY-MONO bar2 peak", "P(bar1/2/3)",
                f"b1={p_b1*100:.4f}% b2={p_b2*100:.4f}% b3={p_b3*100:.4f}%",
                "b2 > b1, b2 > b3", ok))
    # TOP-JACKPOT-ESC m5/m2 ≥ 1.1
    m2_p1 = r2["pay_hits"].get("1", 0)
    m5_p1 = r5["pay_hits"].get("1", 0)
    ratio = m5_p1 / m2_p1 if m2_p1 > 0 else float("inf")
    ok = ratio >= 1.1
    out.append(("TOP-JACKPOT-ESC m5/m2", "wild_pure ratio",
                f"ratio={ratio:.4f}",
                "≥ 1.1", ok))
    # 1000+ m5 ≤ 1e-5
    ok = r5["p_r_ge_1000_per_spin"] <= 1e-5
    out.append(("1000+ m5", "P(R>=1000/spin)",
                f"{r5['p_r_ge_1000_per_spin']:.3e}",
                "≤ 1e-5", ok))
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
    7: {
        "total_rtp": 85.72,
        "base_rtp": 33.74,
        "feature_rtp": 51.98,
        "base_hit": 13.06,
        "trigger": 1.130,
        "r1_blank": 42.35,
        "wild_cadence_1in": 51314,
        "pay_hits": {
            "9": 8.316, "71": 0.245, "4": 0.0023,
            "1": 0.0019, "2": 0.0397, "21": 0.0193,
            "3": 0.0769, "5": 0.3011, "7": 0.4991, "8": 3.557,
        },
        "family_shares": {
            "cherry1": 24.64, "cherry2": 3.63, "cherry3": 0.10,
            "bar1": 11.30, "bar2": 14.55, "bar3": 9.21, "bar_mixed": 24.38,
            "high7": 11.02, "wild_pure": 1.16,
        },
    },
    2: {
        "total_rtp": 290.29,
        "base_rtp": 110.31,
        "feature_rtp": 179.98,
        "base_hit": 33.58,
        "trigger": 3.000,
        "r1_blank": 16.10,
        "wild_cadence_1in": 36364,
        "pay_hits": {
            "9": 19.65, "71": 1.610, "4": 0.0432,
            "1": 0.0028, "2": 0.226, "21": 0.215,
            "3": 0.274, "5": 1.562, "7": 0.479, "8": 9.517,
        },
        "family_shares": {
            "cherry1": 17.81, "cherry2": 7.30, "cherry3": 0.59,
            "bar1": 3.71, "bar2": 20.69, "bar3": 9.03, "bar_mixed": 19.83,
            "high7": 20.54, "wild_pure": 0.50,
        },
    },
    5: {
        "total_rtp": 497.24,
        "base_rtp": 116.15,
        "feature_rtp": 381.10,
        "base_hit": 34.39,
        "trigger": 3.090,
        "r1_blank": 15.39,
        "wild_cadence_1in": 28867,
        "pay_hits": {
            "9": 20.14, "71": 1.704, "4": 0.0472,
            "1": 0.0035, "2": 0.247, "21": 0.215,
            "3": 0.289, "5": 1.614, "7": 0.503, "8": 9.631,
        },
        "family_shares": {
            "cherry1": 17.34, "cherry2": 7.34, "cherry3": 0.61,
            "bar1": 3.79, "bar2": 20.76, "bar3": 9.30, "bar_mixed": 19.23,
            "high7": 21.03, "wild_pure": 0.60,
        },
    },
}


def diff_vs_d(r, mode, *, tol_pp=0.5):
    """Per V/X brief: 0.5pp tolerance for higher-variance lucky modes,
    0.1pp for mode 7. tol_pp passed in."""
    claim = D_CLAIM[mode]
    diffs = []
    diffs.append(("total_rtp", r["total_rtp"], claim["total_rtp"],
                  abs(r["total_rtp"] - claim["total_rtp"])))
    diffs.append(("base_rtp", r["base_rtp"], claim["base_rtp"],
                  abs(r["base_rtp"] - claim["base_rtp"])))
    diffs.append(("feature_rtp", r["feature_rtp"], claim["feature_rtp"],
                  abs(r["feature_rtp"] - claim["feature_rtp"])))
    diffs.append(("base_hit", r["base_hit"], claim["base_hit"],
                  abs(r["base_hit"] - claim["base_hit"])))
    diffs.append(("trigger", r["trigger"], claim["trigger"],
                  abs(r["trigger"] - claim["trigger"])))
    diffs.append(("r1_blank", r["r1_blank"], claim["r1_blank"],
                  abs(r["r1_blank"] - claim["r1_blank"])))
    diffs.append(("wild_cadence", r["wild_cadence"], claim["wild_cadence_1in"],
                  abs(r["wild_cadence"] - claim["wild_cadence_1in"])))
    for pid, claim_hit in claim["pay_hits"].items():
        my = r["pay_hits"].get(pid, 0) * 100
        diffs.append((f"pay_hit[{pid}]", my, claim_hit, abs(my - claim_hit)))
    for fam, claim_share in claim["family_shares"].items():
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
            f"V verifier v14b temp output — DO NOT SHIP. Mode {mode}.",
            "Generated from D's marginals in design_v14b_modes_725.md",
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


# ----------------------------------------------------------------------
# Run verify.py against temp weights
# ----------------------------------------------------------------------

def run_verify_against_tmp():
    """Run verify.py against TMP_ROOT and capture stdout."""
    cmd = [
        sys.executable,
        "-m", "slot_designer.machines.M15.verify",
        "--weights-dir", str(TMP_ROOT),
    ]
    result = subprocess.run(cmd, cwd=str(_ROOT),
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_verify_reds(stdout):
    """Pull RED lines per mode from verify.py output."""
    reds = []
    for line in stdout.splitlines():
        if "[FAIL]" in line:
            reds.append(line.strip())
    return reds


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print("=" * 70)
    print("M15 v14b INDEPENDENT VERIFIER — modes 7/2/5 (M7_F110, M2_Q, M5_H)")
    print("=" * 70)

    # ----- 1. Compute analytic + engine numerics per mode
    results = {}
    weights_by_mode = {}
    margs_by_mode = {1: M1_MARGS, 7: M7_MARGS, 2: M2_MARGS, 5: M5_MARGS}
    for mode in (1, 7, 2, 5):
        analytic = evaluate(margs_by_mode[mode], mode, tag="analytic")
        # Engine: marginals -> integer weights -> mechanism B -> remarginalize
        w_raw = marginals_to_weights(STRIPS, margs_by_mode[mode])
        w_b = apply_mechanism_b_blanks(STRIPS, w_raw)
        engine_margs = reel_marginals_from_weights(STRIPS, w_b)
        engine_r = evaluate(engine_margs, mode, tag="engine")
        results[mode] = {"analytic": analytic, "engine": engine_r}
        weights_by_mode[mode] = w_b

    # ----- 2. Print analytic + engine per mode
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
                print(f"  {k}: {v:.4f}")
        print(f"  P(R>=1000/spin): {r['p_r_ge_1000_per_spin']:.3e}")
        print(f"  P(R>=200/spin):  {r['p_r_ge_200_per_spin']:.3e}")

        print(f"\n--- MODE {mode} ENGINE (after marginals_to_weights + mech B) ---")
        r = results[mode]["engine"]
        for k in ("total_rtp", "base_rtp", "feature_rtp", "hit_session",
                  "base_hit", "trigger", "r1_blank", "r2_blank", "r3_blank",
                  "wild_cadence"):
            v = r[k]
            if k == "wild_cadence":
                print(f"  {k}: 1/{v:.0f}")
            else:
                print(f"  {k}: {v:.4f}")

    # ----- 3. Per-pay-id breakdown (analytic) per mode
    for mode in (1, 7, 2, 5):
        print(f"\n--- MODE {mode} PER-PAY-ID (analytic) ---")
        r = results[mode]["analytic"]
        pid_order = ["9", "71", "4", "1", "2", "21", "3", "5", "7", "8"]
        print(f"  {'pid':>4} {'fam':<12} {'mult':>5} {'hit%':>10} {'1in':>10} {'rtp_pp':>8}")
        for pid in pid_order:
            fam = FAMILY_OF_PAY_ID.get(pid, "?")
            mult = PAY_MULT.get(pid, 0)
            p = r["pay_hits"].get(pid, 0) * 100
            oneinn = (1 / (p / 100)) if p > 0 else float("inf")
            rtp_pp = r["pay_rtp"].get(pid, 0) * 100
            print(f"  {pid:>4} {fam:<12} {mult:>5} {p:>9.4f}% {oneinn:>10.0f} "
                  f"{rtp_pp:>7.3f}")

    # ----- 4. Cross-mode invariants (manual)
    r1 = results[1]["analytic"]
    r7 = results[7]["analytic"]
    r2 = results[2]["analytic"]
    r5 = results[5]["analytic"]

    print("\n\n========================================")
    print("CROSS-MODE INVARIANTS (analytic)")
    print("========================================")

    print("\n--- MODE 7 invariants ---")
    m7_checks = check_mode7_invariants(r7, r1) + jackpot_check(r7)
    for cat, label, val, expected, ok in m7_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:25} {label:30}  got: {val}  expected: {expected}")
    n7_fail = sum(1 for *_, ok in m7_checks if not ok)

    print("\n--- MODE 2 invariants ---")
    m2_checks = check_mode2_invariants(r2, r1) + jackpot_check(r2)
    for cat, label, val, expected, ok in m2_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:25} {label:30}  got: {val}  expected: {expected}")
    n2_fail = sum(1 for *_, ok in m2_checks if not ok)

    print("\n--- MODE 5 invariants ---")
    m5_checks = check_mode5_invariants(r5, r2, r1) + jackpot_check(r5)
    for cat, label, val, expected, ok in m5_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:25} {label:30}  got: {val}  expected: {expected}")
    n5_fail = sum(1 for *_, ok in m5_checks if not ok)

    # ----- 5. Diff vs D's claims
    print("\n\n========================================")
    print("DIFF vs D's claims")
    print("========================================")
    diffs_summary = {}
    for mode in (7, 2, 5):
        tol = 0.1 if mode == 7 else 0.5
        print(f"\n--- MODE {mode} diff (tol {tol}pp) ---")
        r = results[mode]["analytic"]
        diffs = diff_vs_d(r, mode, tol_pp=tol)
        large = []
        for name, my, dv, delta in diffs:
            # Cadence and wild cadence get special tolerance
            if name == "wild_cadence":
                ok = delta <= max(2000, abs(dv) * 0.1)
            elif "pay_hit" in name or "family_share" in name:
                ok = delta <= max(tol, abs(dv) * 0.02)
            else:
                ok = delta <= tol
            flag = "OK" if ok else "DIFF"
            if not ok:
                large.append((name, my, dv, delta))
            print(f"  {flag:4}  {name:<24}  mine={my:>12.4f}  D={dv:>12.4f}  "
                  f"delta={delta:>10.4f}")
        diffs_summary[mode] = sorted(large, key=lambda x: -x[3])[:5]
        if large:
            print(f"  TOP DIFFS:")
            for name, mine, dv, delta in diffs_summary[mode][:3]:
                print(f"    {name}: mine={mine:.4f} D={dv:.4f} delta={delta:.4f}")

    # ----- 6. Write temp weights for verify.py
    print("\n\n========================================")
    print("WRITE TEMP WEIGHTS (engine = after mech B)")
    print("========================================")
    for mode in (1, 2, 5, 7):
        w = weights_by_mode[mode]
        fp = FP_BY_MODE[mode]
        p = write_temp_weights(mode, w, feature_params=fp)
        print(f"  mode {mode}: {p}")

    # ----- 7. Run verify.py
    print("\n\n========================================")
    print("RUN verify.py against temp weights")
    print("========================================")
    rc, stdout, stderr = run_verify_against_tmp()
    print(f"\nexit_code: {rc}")
    if stderr.strip():
        print(f"\nSTDERR (truncated):")
        for line in stderr.splitlines()[:40]:
            print(f"  {line}")
    # Save the full stdout to a log
    log_path = TMP_ROOT / "verify_output.txt"
    log_path.write_text(stdout, encoding="utf-8")
    print(f"\nFull verify.py output written: {log_path}")

    reds = parse_verify_reds(stdout)
    print(f"\n{len(reds)} RED line(s):")
    for line in reds:
        print(f"  {line}")

    # ----- 8. Final summary
    print("\n\n========================================")
    print("V14b FINAL SUMMARY")
    print("========================================")
    print(f"\nMode 7 invariant fails (analytic): {n7_fail}")
    print(f"Mode 2 invariant fails (analytic): {n2_fail}")
    print(f"Mode 5 invariant fails (analytic): {n5_fail}")
    print(f"verify.py exit_code: {rc}")
    print(f"verify.py RED lines: {len(reds)}")

    print("\n--- Engine RTP per mode (after integer rounding + mech B) ---")
    for mode in (1, 7, 2, 5):
        r = results[mode]["engine"]
        print(f"  mode {mode}: total_rtp={r['total_rtp']:.3f}pp  "
              f"base_hit={r['base_hit']:.3f}%  R1_blank={r['r1_blank']:.3f}%  "
              f"wild_cadence=1/{r['wild_cadence']:.0f}")

    return {
        "results": results,
        "m7_checks": m7_checks,
        "m2_checks": m2_checks,
        "m5_checks": m5_checks,
        "diffs": diffs_summary,
        "verify_rc": rc,
        "verify_reds": reds,
        "weights": weights_by_mode,
    }


if __name__ == "__main__":
    main()
