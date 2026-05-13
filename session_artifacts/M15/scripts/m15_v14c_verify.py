"""M15 v14c modes 2/5 — INDEPENDENT VERIFIER (2026-05-12).

Verifies D's M2_LC and M5_LC_plus candidates from design_v14c_modes_25.md
WITHOUT importing D's design script. Takes each mode's marginals as
**direct numeric input** from the design doc tables (§2.2, §3.2),
recomputes integer per-stop weights via local primitives, runs
analytic_profile_from_marginals, and exercises verify.py against the
resulting temp weights.

Special focus per V brief:
  - D self-flagged: m5 hit margin 0.04pp + m5 trigger equal m2 trigger
    (both at risk of integer rounding flipping). This script reports
    engine-realized values explicitly for both.
  - All 12 cross-mode invariants checked independently.
  - verify.py REDs classified.

DOES NOT modify production files. Writes temp weights to
`session_artifacts/M15/_tmp_v14c_verify/mode_{1,2,5,7}/weights.json`.
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

TMP_ROOT = _ROOT / "session_artifacts" / "M15" / "_tmp_v14c_verify"

# ----------------------------------------------------------------------
# D's M2_LC and M5_LC_plus marginals — taken DIRECTLY from
# design_v14c_modes_25.md §2.2 and §3.2 tables. DO NOT import from D's
# script.
# ----------------------------------------------------------------------

# Mode 1 (shipped C38_C14) — for cross-mode comparison only.
# From design_v14c_modes_25.md §4.1 table + design_v14c_design_modes_25.py
# M1_MARGINALS (verified byte-equal to shipped state).
M1_R1 = {"blank": 0.3852, "cherry": 0.0400, "1bar": 0.2019, "2bar": 0.1648,
         "3bar": 0.1032, "high7": 0.0720, "doublediamond": 0.0290,
         "jackpot": 0.0040}
M1_R2 = {"blank": 0.5026, "cherry": 0.0350, "1bar": 0.1651, "2bar": 0.1353,
         "3bar": 0.0729, "high7": 0.0571, "doublediamond": 0.0280,
         "jackpot": 0.0040}
M1_R3 = {"blank": 0.5901, "cherry": 0.0250, "1bar": 0.1349, "2bar": 0.1099,
         "3bar": 0.0549, "high7": 0.0470, "doublediamond": 0.0240,
         "topdollar": 0.0112, "jackpot": 0.0030}

# Mode 7 (shipped M7_F110) — from design_v14b_modes_725.md §2.2.
M7_R1 = {"blank": 0.42323, "cherry": 0.03700, "1bar": 0.18697, "2bar": 0.15252,
         "3bar": 0.09534, "high7": 0.07198, "doublediamond": 0.02898,
         "jackpot": 0.004}
M7_R2 = {"blank": 0.55289, "cherry": 0.03077, "1bar": 0.14470, "2bar": 0.11847,
         "3bar": 0.06405, "high7": 0.05707, "doublediamond": 0.02796,
         "jackpot": 0.004}
M7_R3 = {"blank": 0.64863, "cherry": 0.02040, "1bar": 0.11045, "2bar": 0.09001,
         "3bar": 0.04500, "high7": 0.04704, "doublediamond": 0.02401,
         "topdollar": 0.01122, "jackpot": 0.003}

# Mode 2 M2_LC — from design_v14c_modes_25.md §2.2 per-reel marginals table.
# These are PERCENT values in the doc; converted to fractions here.
# Row sums: 100.000% exact per doc.
M2_R1 = {"blank": 0.27528, "cherry": 0.06400, "1bar": 0.21805, "2bar": 0.17798,
         "3bar": 0.11146, "high7": 0.12168, "doublediamond": 0.02755,
         "jackpot": 0.004}
M2_R2 = {"blank": 0.24777, "cherry": 0.06300, "1bar": 0.23774, "2bar": 0.19483,
         "3bar": 0.10498, "high7": 0.12248, "doublediamond": 0.02520,
         "jackpot": 0.004}
M2_R3 = {"blank": 0.23190, "cherry": 0.05000, "1bar": 0.24282, "2bar": 0.19782,
         "3bar": 0.09882, "high7": 0.12220, "doublediamond": 0.02040,
         "topdollar": 0.03304, "jackpot": 0.003}

# Mode 5 M5_LC_plus — from design_v14c_modes_25.md §3.2 per-reel marginals table.
M5_R1 = {"blank": 0.28642, "cherry": 0.06400, "1bar": 0.21805, "2bar": 0.17798,
         "3bar": 0.11146, "high7": 0.11195, "doublediamond": 0.02617,
         "jackpot": 0.004}
M5_R2 = {"blank": 0.25879, "cherry": 0.06300, "1bar": 0.23774, "2bar": 0.19483,
         "3bar": 0.10498, "high7": 0.11268, "doublediamond": 0.02772,
         "jackpot": 0.004}
M5_R3 = {"blank": 0.23964, "cherry": 0.05000, "1bar": 0.24282, "2bar": 0.19782,
         "3bar": 0.09882, "high7": 0.11242, "doublediamond": 0.02244,
         "topdollar": 0.03304, "jackpot": 0.003}


def normalize_margs(d):
    """Recompute blank as residual; sum to 1 exactly."""
    out = dict(d)
    nb = sum(v for k, v in out.items() if k != "blank")
    if nb > 1.0:
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
# Local reimpl; byte-for-byte same as M15 v8.1 mechanism B + helpers.
# ----------------------------------------------------------------------

def marginals_to_weights(strips, margs, scale=10000):
    """Map per-reel symbol marginal fractions -> integer per-stop weights.

    For each reel: integer weight per stop of symbol s = round(scale * marg[s] / cnt[s]),
    where cnt[s] is the stop count of s on the strip. Minimum weight 1."""
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
    """v8.1 mechanism B: shift weight from non-top-adj blanks to top-adj blanks.

    Total Blank weight per reel preserved -> marginals unchanged -> RTP/hit/share
    invariant. Top-symbol any-reel window visibility lifted."""
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
    """Recompute per-reel symbol marginals from integer per-stop weights."""
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
    # LUCKY-MONO m2 trigger >= m1
    ok = r2["trigger_frac"] >= r1["trigger_frac"] - 1e-12
    out.append(("LUCKY-MONO m2>=m1 trig", "trigger",
                f"m2={r2['trigger']:.4f}% m1={r1['trigger']:.4f}%",
                "m2 ≥ m1", ok))
    # Bar §1 hierarchy P(b1) > P(b2) > P(b3) (per design intent v14c)
    p_b1 = r2["pay_hits"].get("7", 0)
    p_b2 = r2["pay_hits"].get("5", 0)
    p_b3 = r2["pay_hits"].get("3", 0)
    ok = p_b1 > p_b2 > p_b3
    out.append(("BAR-HIER-§1 m2", "P(b1)>P(b2)>P(b3)",
                f"b1={p_b1*100:.4f}% b2={p_b2*100:.4f}% b3={p_b3*100:.4f}%",
                "b1 > b2 > b3", ok))
    # TOP-JACKPOT-CADENCE m2/m1 <= 1.5
    m1_p1 = r1["pay_hits"].get("1", 0)
    m2_p1 = r2["pay_hits"].get("1", 0)
    ratio = m2_p1 / m1_p1 if m1_p1 > 0 else float("inf")
    ok = ratio <= 1.5
    out.append(("TOP-JACKPOT-CADENCE m2/m1", "wild_pure ratio",
                f"ratio={ratio:.4f}",
                "≤ 1.5", ok))
    # 1000+ m2 ≤ 1e-5
    ok = r2["p_r_ge_1000_per_spin"] <= 1e-5
    out.append(("1000+ m2", "P(R>=1000/spin)",
                f"{r2['p_r_ge_1000_per_spin']:.3e}",
                "≤ 1e-5", ok))
    # REEL-ASYM-LUCKY R1 blank >= R3 blank
    ok = r2["r1_blank"] >= r2["r3_blank"]
    out.append(("REEL-ASYM-LUCKY m2", "R1>=R3 blank",
                f"R1={r2['r1_blank']:.2f} R3={r2['r3_blank']:.2f}",
                "R1 ≥ R3", ok))
    # FAM-SHARE m2 cherry1 [15,25]
    ok = 15.0 <= r2["family_shares"].get("cherry1", 0) <= 25.0
    out.append(("FAM-SHARE m2 c1", "cherry1 share-of-base",
                f"{r2['family_shares'].get('cherry1', 0):.2f}%",
                "[15, 25]", ok))
    # FAM-SHARE m2 bar3 [5,22]
    ok = 5.0 <= r2["family_shares"].get("bar3", 0) <= 22.0
    out.append(("FAM-SHARE m2 b3", "bar3 share-of-base",
                f"{r2['family_shares'].get('bar3', 0):.2f}%",
                "[5, 22]", ok))
    # FAM-SHARE m2 high7 [14,30]
    ok = 14.0 <= r2["family_shares"].get("high7", 0) <= 30.0
    out.append(("FAM-SHARE m2 h7", "high7 share-of-base",
                f"{r2['family_shares'].get('high7', 0):.2f}%",
                "[14, 30]", ok))
    # FAM-SHARE m2 wild [0.08, 0.30]
    ok = 0.08 <= r2["family_shares"].get("wild_pure", 0) <= 0.30
    out.append(("FAM-SHARE m2 wld", "wild_pure share-of-base",
                f"{r2['family_shares'].get('wild_pure', 0):.3f}%",
                "[0.08, 0.30]", ok))
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
    # LUCKY-MONO m5 >= m2 hit (focus on tight margin)
    ok = r5["base_hit"] >= r2["base_hit"] - 1e-9
    out.append(("LUCKY-MONO m5>=m2 hit", "hit",
                f"m5={r5['base_hit']:.5f}% m2={r2['base_hit']:.5f}% diff={(r5['base_hit']-r2['base_hit']):+.5f}pp",
                "m5 ≥ m2", ok))
    # LUCKY-MONO m5 >= m2 trig (focus on equality)
    ok = r5["trigger_frac"] >= r2["trigger_frac"] - 1e-9
    out.append(("LUCKY-MONO m5>=m2 trig", "trigger",
                f"m5={r5['trigger']:.5f}% m2={r2['trigger']:.5f}% diff={(r5['trigger_frac']-r2['trigger_frac'])*100:+.5f}pp",
                "m5 ≥ m2", ok))
    # Bar §1 hierarchy P(b1) > P(b2) > P(b3)
    p_b1 = r5["pay_hits"].get("7", 0)
    p_b2 = r5["pay_hits"].get("5", 0)
    p_b3 = r5["pay_hits"].get("3", 0)
    ok = p_b1 > p_b2 > p_b3
    out.append(("BAR-HIER-§1 m5", "P(b1)>P(b2)>P(b3)",
                f"b1={p_b1*100:.4f}% b2={p_b2*100:.4f}% b3={p_b3*100:.4f}%",
                "b1 > b2 > b3", ok))
    # TOP-JACKPOT-CADENCE m5/m2 ≥ 1.1
    m2_p1 = r2["pay_hits"].get("1", 0)
    m5_p1 = r5["pay_hits"].get("1", 0)
    ratio = m5_p1 / m2_p1 if m2_p1 > 0 else float("inf")
    ok = ratio >= 1.1
    out.append(("TOP-JACKPOT-CADENCE m5/m2", "wild_pure ratio",
                f"ratio={ratio:.4f}",
                "≥ 1.1", ok))
    # 1000+ m5 ≤ 1e-5
    ok = r5["p_r_ge_1000_per_spin"] <= 1e-5
    out.append(("1000+ m5", "P(R>=1000/spin)",
                f"{r5['p_r_ge_1000_per_spin']:.3e}",
                "≤ 1e-5", ok))
    # REEL-ASYM-LUCKY m5 R1>=R3 blank
    ok = r5["r1_blank"] >= r5["r3_blank"]
    out.append(("REEL-ASYM-LUCKY m5", "R1>=R3 blank",
                f"R1={r5['r1_blank']:.2f} R3={r5['r3_blank']:.2f}",
                "R1 ≥ R3", ok))
    # FAM-SHARE m5 bar3 [5,22]
    ok = 5.0 <= r5["family_shares"].get("bar3", 0) <= 22.0
    out.append(("FAM-SHARE m5 b3", "bar3 share-of-base",
                f"{r5['family_shares'].get('bar3', 0):.2f}%",
                "[5, 22]", ok))
    return out


def check_cross_mode_ladder(r1, r2, r5, r7):
    out = []
    # RTP ladder: m5 > m2 > m1 > m7
    out.append(("RTP-LADDER m7<m1", "m7 < m1",
                f"{r7['total_rtp']:.2f} < {r1['total_rtp']:.2f}",
                "m7 < m1", r7["total_rtp"] < r1["total_rtp"]))
    out.append(("RTP-LADDER m1<m2", "m1 < m2",
                f"{r1['total_rtp']:.2f} < {r2['total_rtp']:.2f}",
                "m1 < m2", r1["total_rtp"] < r2["total_rtp"]))
    out.append(("RTP-LADDER m2<m5", "m2 < m5",
                f"{r2['total_rtp']:.2f} < {r5['total_rtp']:.2f}",
                "m2 < m5", r2["total_rtp"] < r5["total_rtp"]))
    # Hit ladder: m5 >= m2 > m1 > m7
    out.append(("HIT-LADDER m7<m1", "m7 < m1",
                f"{r7['base_hit']:.3f} < {r1['base_hit']:.3f}",
                "m7 < m1", r7["base_hit"] < r1["base_hit"]))
    out.append(("HIT-LADDER m1<m2", "m1 < m2",
                f"{r1['base_hit']:.3f} < {r2['base_hit']:.3f}",
                "m1 < m2", r1["base_hit"] < r2["base_hit"]))
    out.append(("HIT-LADDER m5>=m2", "m5 >= m2",
                f"{r5['base_hit']:.5f} >= {r2['base_hit']:.5f} (diff {r5['base_hit']-r2['base_hit']:+.5f})",
                "m5 ≥ m2", r5["base_hit"] >= r2["base_hit"] - 1e-9))
    # Trigger ladder: m7 ~ m1; m1 < m2; m2 <= m5
    diff = abs(r7["trigger_frac"] - r1["trigger_frac"])
    out.append(("TRIG-LADDER m7~m1", "diff ≤ 5e-4",
                f"|{r7['trigger']:.4f} - {r1['trigger']:.4f}| = {diff:.6f}",
                "≤ 5e-4", diff <= 5e-4))
    out.append(("TRIG-LADDER m1<m2", "m1 < m2",
                f"{r1['trigger']:.4f} < {r2['trigger']:.4f}",
                "m1 < m2", r2["trigger_frac"] > r1["trigger_frac"]))
    out.append(("TRIG-LADDER m5>=m2", "m5 >= m2",
                f"{r5['trigger']:.6f} >= {r2['trigger']:.6f} (diff {(r5['trigger_frac']-r2['trigger_frac'])*100:+.6f})",
                "m5 ≥ m2", r5["trigger_frac"] >= r2["trigger_frac"] - 1e-9))
    # TOP-JACKPOT-ESC: m1 < m2 < m5
    out.append(("TOP-JACKPOT-ESC m1<m2<m5", "P(R>=200)/spin",
                f"{r1['p_r_ge_200_per_spin']:.3e} < {r2['p_r_ge_200_per_spin']:.3e} < {r5['p_r_ge_200_per_spin']:.3e}",
                "m1 < m2 < m5",
                r1["p_r_ge_200_per_spin"] < r2["p_r_ge_200_per_spin"] < r5["p_r_ge_200_per_spin"]))
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
    2: {
        "total_rtp": 296.13,
        "base_rtp": 97.91,
        "feature_rtp": 198.21,
        "base_hit": 33.85,
        "trigger": 3.304,
        "r1_blank": 27.53,
        "r3_blank": 23.19,
        "wild_cadence_1in": 70607,
        "pay_hits": {
            "9": 15.6841, "71": 0.9777, "4": 0.0202,
            "1": 0.0014, "2": 0.1307, "21": 0.1821,
            "3": 0.2143, "5": 0.9855, "7": 1.6984, "8": 13.9575,
        },
        "family_shares": {
            "cherry1": 16.02, "cherry2": 4.99, "cherry3": 0.31,
            "bar1": 11.34, "bar2": 13.81, "bar3": 7.15, "bar_mixed": 31.17,
            "high7": 14.92, "wild_pure": 0.289,
        },
        "p_r_ge_1000_per_spin": 1.539e-6,
        "p_r_ge_200_per_spin": 2.82e-4,
    },
    5: {
        "total_rtp": 504.56,
        "base_rtp": 97.08,
        "feature_rtp": 407.48,
        "base_hit": 33.89,
        "trigger": 3.304,
        "r1_blank": 28.64,
        "r3_blank": 23.96,
        "wild_cadence_1in": 61377,
        "pay_hits": {
            "9": 15.6841, "71": 0.9777, "4": 0.0202,
            "1": 0.0016, "2": 0.1181, "21": 0.1418,
            "3": 0.2198, "5": 0.9991, "7": 1.7181, "8": 14.0118,
        },
        "family_shares": {
            "cherry1": 16.16, "cherry2": 5.04, "cherry3": 0.31,
            "bar1": 11.68, "bar2": 14.28, "bar3": 7.51, "bar_mixed": 31.66,
            "high7": 13.03, "wild_pure": 0.34,
        },
        "p_r_ge_1000_per_spin": 1.100e-7,
        "p_r_ge_200_per_spin": 3.89e-3,
    },
}


def diff_vs_d(r, mode, *, tol_pp=0.5):
    """Numeric diff vs D's claims. Per V brief: 0.5pp tolerance for lucky modes."""
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
    diffs.append(("r3_blank", r["r3_blank"], claim["r3_blank"],
                  abs(r["r3_blank"] - claim["r3_blank"])))
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
            f"V verifier v14c temp output — DO NOT SHIP. Mode {mode}.",
            "Generated from D's marginals in design_v14c_modes_25.md",
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
    print("M15 v14c INDEPENDENT VERIFIER — modes 2/5 (M2_LC, M5_LC_plus)")
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
                print(f"  {k}: {v:.5f}")
        print(f"  P(R>=1000/spin): {r['p_r_ge_1000_per_spin']:.3e}")
        print(f"  P(R>=200/spin):  {r['p_r_ge_200_per_spin']:.3e}")

        print(f"\n--- MODE {mode} ENGINE (post marginals_to_weights + mech B) ---")
        r = results[mode]["engine"]
        for k in ("total_rtp", "base_rtp", "feature_rtp", "hit_session",
                  "base_hit", "trigger", "r1_blank", "r2_blank", "r3_blank",
                  "wild_cadence"):
            v = r[k]
            if k == "wild_cadence":
                print(f"  {k}: 1/{v:.0f}")
            else:
                print(f"  {k}: {v:.5f}")

    # ----- 3. Per-pay-id (analytic) per mode
    for mode in (2, 5):
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
                  f"{rtp_pp:>7.4f}")

    # ----- 4. Cross-mode invariants (analytic)
    r1 = results[1]["analytic"]
    r7 = results[7]["analytic"]
    r2 = results[2]["analytic"]
    r5 = results[5]["analytic"]

    print("\n\n========================================")
    print("CROSS-MODE INVARIANTS (analytic)")
    print("========================================")

    print("\n--- MODE 2 invariants ---")
    m2_checks = check_mode2_invariants(r2, r1) + jackpot_check(r2)
    for cat, label, val, expected, ok in m2_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:30} {label:30}  got: {val}  expected: {expected}")
    n2_fail = sum(1 for *_, ok in m2_checks if not ok)

    print("\n--- MODE 5 invariants ---")
    m5_checks = check_mode5_invariants(r5, r2, r1) + jackpot_check(r5)
    for cat, label, val, expected, ok in m5_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:30} {label:30}  got: {val}  expected: {expected}")
    n5_fail = sum(1 for *_, ok in m5_checks if not ok)

    print("\n--- Cross-mode ladder ---")
    cm_checks = check_cross_mode_ladder(r1, r2, r5, r7)
    for cat, label, val, expected, ok in cm_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:30} {label:30}  got: {val}  expected: {expected}")
    ncm_fail = sum(1 for *_, ok in cm_checks if not ok)

    # ----- 4b. Same cross-mode ladders ENGINE-realized (post integer rounding + mech B)
    print("\n\n========================================")
    print("CROSS-MODE INVARIANTS (ENGINE-REALIZED, post mech B)")
    print("========================================")
    e1 = results[1]["engine"]
    e7 = results[7]["engine"]
    e2 = results[2]["engine"]
    e5 = results[5]["engine"]

    print("\n--- MODE 2 ENGINE invariants ---")
    e2_checks = check_mode2_invariants(e2, e1) + jackpot_check(e2)
    for cat, label, val, expected, ok in e2_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:30} {label:30}  got: {val}  expected: {expected}")
    e2_fail = sum(1 for *_, ok in e2_checks if not ok)

    print("\n--- MODE 5 ENGINE invariants ---")
    e5_checks = check_mode5_invariants(e5, e2, e1) + jackpot_check(e5)
    for cat, label, val, expected, ok in e5_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:30} {label:30}  got: {val}  expected: {expected}")
    e5_fail = sum(1 for *_, ok in e5_checks if not ok)

    print("\n--- Cross-mode ENGINE ladder ---")
    e_cm_checks = check_cross_mode_ladder(e1, e2, e5, e7)
    for cat, label, val, expected, ok in e_cm_checks:
        st = "PASS" if ok else "FAIL"
        print(f"  [{st}] {cat:30} {label:30}  got: {val}  expected: {expected}")
    e_cm_fail = sum(1 for *_, ok in e_cm_checks if not ok)

    # ----- 5. SPECIAL FOCUS: tight LUCKY-MONO margins
    print("\n\n========================================")
    print("SPECIAL FOCUS: m5 LUCKY-MONO TIGHT MARGINS")
    print("========================================")
    print(f"\nm5 HIT vs m2 HIT (analytic):  m5={r5['base_hit']:.6f}%  m2={r2['base_hit']:.6f}%  diff={r5['base_hit']-r2['base_hit']:+.6f}pp")
    print(f"m5 HIT vs m2 HIT (engine):    m5={e5['base_hit']:.6f}%  m2={e2['base_hit']:.6f}%  diff={e5['base_hit']-e2['base_hit']:+.6f}pp")
    if e5["base_hit"] >= e2["base_hit"]:
        print("  -> LUCKY-MONO HIT engine-realized PASS")
    else:
        print(f"  -> *** LUCKY-MONO HIT engine-realized FAIL: m5 < m2 by {e2['base_hit']-e5['base_hit']:.6f}pp ***")

    print(f"\nm5 TRIG vs m2 TRIG (analytic):  m5={r5['trigger']:.6f}%  m2={r2['trigger']:.6f}%  diff={(r5['trigger_frac']-r2['trigger_frac'])*100:+.6f}pp")
    print(f"m5 TRIG vs m2 TRIG (engine):    m5={e5['trigger']:.6f}%  m2={e2['trigger']:.6f}%  diff={(e5['trigger_frac']-e2['trigger_frac'])*100:+.6f}pp")
    if e5["trigger_frac"] >= e2["trigger_frac"] - 1e-12:
        print("  -> LUCKY-MONO TRIG engine-realized PASS")
    else:
        print(f"  -> *** LUCKY-MONO TRIG engine-realized FAIL: m5 < m2 by {(e2['trigger_frac']-e5['trigger_frac'])*100:.6f}pp ***")

    # ----- 6. Diff vs D's claims
    print("\n\n========================================")
    print("DIFF vs D's claims")
    print("========================================")
    diffs_summary = {}
    for mode in (2, 5):
        tol = 0.5
        print(f"\n--- MODE {mode} diff (analytic; tol {tol}pp) ---")
        r = results[mode]["analytic"]
        diffs = diff_vs_d(r, mode, tol_pp=tol)
        large = []
        for name, my, dv, delta in diffs:
            if name == "wild_cadence":
                ok = delta <= max(2000, abs(dv) * 0.05)
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

    # ----- 7. Write temp weights for verify.py
    print("\n\n========================================")
    print("WRITE TEMP WEIGHTS (engine = post mech B integer)")
    print("========================================")
    for mode in (1, 2, 5, 7):
        w = weights_by_mode[mode]
        fp = FP_BY_MODE[mode]
        p = write_temp_weights(mode, w, feature_params=fp)
        print(f"  mode {mode}: {p}")

    # ----- 8. Run verify.py
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

    # ----- 9. Final summary
    print("\n\n========================================")
    print("V14c FINAL SUMMARY")
    print("========================================")
    print(f"\nAnalytic invariant fails:")
    print(f"  Mode 2: {n2_fail}")
    print(f"  Mode 5: {n5_fail}")
    print(f"  Cross-mode ladder: {ncm_fail}")
    print(f"\nEngine-realized (post integer rounding + mech B) invariant fails:")
    print(f"  Mode 2: {e2_fail}")
    print(f"  Mode 5: {e5_fail}")
    print(f"  Cross-mode ladder: {e_cm_fail}")
    print(f"\nverify.py exit_code: {rc}")
    print(f"verify.py RED lines: {len(reds)}")

    print("\n--- Analytic vs engine RTP/hit/trigger per mode (drift analysis) ---")
    for mode in (1, 7, 2, 5):
        a = results[mode]["analytic"]
        e = results[mode]["engine"]
        print(f"  mode {mode}: RTP {a['total_rtp']:.3f} -> {e['total_rtp']:.3f} (drift {e['total_rtp']-a['total_rtp']:+.3f}pp)  "
              f"hit {a['base_hit']:.4f} -> {e['base_hit']:.4f} (drift {e['base_hit']-a['base_hit']:+.4f}pp)  "
              f"trig {a['trigger']:.4f} -> {e['trigger']:.4f} (drift {e['trigger']-a['trigger']:+.4f}pp)")

    return {
        "results": results,
        "m2_checks": m2_checks,
        "m5_checks": m5_checks,
        "cm_checks": cm_checks,
        "e2_checks": e2_checks,
        "e5_checks": e5_checks,
        "e_cm_checks": e_cm_checks,
        "diffs": diffs_summary,
        "verify_rc": rc,
        "verify_reds": reds,
        "weights": weights_by_mode,
    }


if __name__ == "__main__":
    main()
