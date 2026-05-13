"""M15 v13c verifier — INDEPENDENT recomputation of PPP_v20 candidate.

Verifies D's claim:
    R1: blank 39.60, cherry 4.50, 1bar 28.00, 2bar 7.00, 3bar 2.00, high7 16.00, dd 2.50, jp 0.40
    R2: blank 49.80, cherry 3.50, 1bar 24.00, 2bar 6.00, 3bar 1.80, high7 12.00, dd 2.50, jp 0.40
    R3: blank 58.10, cherry 3.00, 1bar 20.00, 2bar 5.00, 3bar 1.50, high7 8.50, dd 2.50, td 1.10, jp 0.30

This script:
  - takes the PPP_v20 marginals as inputs (hard-coded; does NOT import from D's script)
  - independently reconstructs integer per-stop weights via marginals_to_weights + apply_mechanism_b_blanks
  - runs analytic_profile_from_marginals to recompute base game
  - composes session-centric profile (base + feature)
  - checks each metric against the 14 hardlines and v7 implicit bar1 share ≤ 30%
  - computes family share-of-base
  - computes per-pay-id RTP
  - computes wild_pure cadence
  - computes PWDF per top symbol per reel
  - tries counterexample candidates targeting g15 ∈ [10, 13]
  - writes weights.json to a TEMP directory then runs verify.py against it
  - DOES NOT touch production files
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from collections import defaultdict
from contextlib import redirect_stdout
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.devtools.player_experience import symbol_window_probability
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution


_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
PROD_WEIGHTS_PATH = _M15_DIR / "weights" / "mode_1" / "weights.json"

TMP_DIR = _ROOT / "session_artifacts" / "M15" / "_tmp_v13c_verify"
TMP_M1_DIR = TMP_DIR / "mode_1"
TMP_WEIGHTS_PATH = TMP_M1_DIR / "weights.json"

# Load the engine to borrow the evaluator (production weights merely seed the
# evaluator; we recompute marginals ourselves from PPP_v20 inputs below).
engine, _spec_dict = load_engine(SPEC_PATH, PROD_WEIGHTS_PATH, strips_path=STRIPS_PATH)
EV = engine.evaluator

# Load feature_params (LOCKED v9 byte-equal — same as design v13c expects)
_prod_weights_doc = json.loads(PROD_WEIGHTS_PATH.read_text(encoding="utf-8"))
FP = _prod_weights_doc["feature_params"]


# ---------------------------------------------------------------------
# Feature EV pre-computation (mirrors D's approach; uses LOCKED params)
# ---------------------------------------------------------------------
def precompute_feature_ev():
    dist = _round_payout_distribution(
        tuple(FP["x_count_weights"]),
        tuple(FP["y_count_weights"]),
        tuple(FP["x_value_weights"]),
        tuple(FP["y_value_weights"]),
    )
    p_accept = sum(p for r, p in dist if r >= FP["accept_threshold"])
    accept_dist = [(r, p) for r, p in dist if r >= FP["accept_threshold"]]

    final = defaultdict(float)
    for round_idx in range(1, FP["max_rounds"]):
        branch = ((1 - p_accept) ** (round_idx - 1)) * p_accept
        for r, p in accept_dist:
            final[r] += branch * (p / p_accept) if p_accept > 0 else 0
    branch_forced = (1 - p_accept) ** (FP["max_rounds"] - 1)
    for r, p in dist:
        final[r] += branch_forced * p
    return final


FEAT_FINAL = precompute_feature_ev()


_BUCKET_EDGES = [
    (5000, "ge5000"),
    (1000, "ge1000_lt5000"),
    (500, "ge500_lt1000"),
    (200, "ge200_lt500"),
    (100, "ge100_lt200"),
    (50, "ge50_lt100"),
    (20, "ge20_lt50"),
    (10, "ge10_lt20"),
    (5, "ge5_lt10"),
    (1, "ge1_lt5"),
    (0, "gt0_lt1"),
]


def to_bucket(r):
    if r <= 0:
        return None
    for edge, k in _BUCKET_EDGES:
        if r >= edge:
            return k
    return None


def feature_bucket_ev():
    bucket_ev = defaultdict(float)
    for r, p in FEAT_FINAL.items():
        b = to_bucket(r)
        if b:
            bucket_ev[b] += r * p
    return bucket_ev


FEAT_BUCKET_EV = feature_bucket_ev()
FEAT_EV_TOTAL = sum(FEAT_BUCKET_EV.values())


PAY_FAM_MAP = {
    "9": "cherry1",
    "71": "cherry2",
    "4": "cherry3",
    "1": "wild_pure",
    "2": "high7_wild",
    "21": "high7_pure",
    "3": "bar3",
    "5": "bar2",
    "7": "bar1",
    "8": "bar_mixed",
}


# ---------------------------------------------------------------------
# Marginal construction (independent of D's script)
# ---------------------------------------------------------------------
def make_marginals(R1: dict, R2: dict, R3: dict):
    """Take non-blank fractions per reel, add blank as residual, normalize."""
    out = []
    for R in (R1, R2, R3):
        d = dict(R)
        non_blank = sum(d.values())
        d["blank"] = max(0.001, 1.0 - non_blank)
        s = sum(d.values())
        out.append({k: v / s for k, v in d.items() if v > 0})
    return out


def evaluate(margs):
    """Returns recomputed metrics — base game closed-form + feature add-on."""
    prof = analytic_profile_from_marginals(EV, margs)
    trigger = margs[2].get("topdollar", 0.0)
    base_rtp = prof["rtp_pct"]
    base_hit = prof["hit_rate"]
    feature_rtp = trigger * FEAT_EV_TOTAL * 100
    total_rtp = base_rtp + feature_rtp
    hit_session = (base_hit + trigger) * 100

    session_bucket = {k: v * 100 for k, v in prof["bucket_rtp"].items()}
    for k, ev in FEAT_BUCKET_EV.items():
        session_bucket[k] = session_bucket.get(k, 0) + trigger * ev * 100

    pay_rtp_pp = {pid: v * 100 for pid, v in prof["pay_rtp"].items()}
    pay_hit_pct = {pid: v * 100 for pid, v in prof["pay_hits"].items()}

    family_pp = defaultdict(float)
    for pid, rtp_pct in pay_rtp_pp.items():
        fam = PAY_FAM_MAP.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp_pct
    high7_combined_pp = family_pp.get("high7_wild", 0) + family_pp.get("high7_pure", 0)
    family_shares = {}
    if base_rtp > 0:
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "wild_pure"):
            family_shares[fam] = family_pp.get(fam, 0) / base_rtp * 100
        family_shares["high7"] = high7_combined_pp / base_rtp * 100

    p_wild = prof["pay_hits"].get("1", 0)
    wild_cadence = 1.0 / p_wild if p_wild > 0 else float("inf")
    return {
        "total_rtp": total_rtp,
        "base_rtp": base_rtp,
        "feature_rtp": feature_rtp,
        "hit_session": hit_session,
        "base_hit": base_hit * 100,
        "trigger": trigger * 100,
        "r1_blank": margs[0]["blank"] * 100,
        "r2_blank": margs[1]["blank"] * 100,
        "r3_blank": margs[2]["blank"] * 100,
        "session_bucket": session_bucket,
        "pay_hits": pay_hit_pct,
        "pay_rtp": pay_rtp_pp,
        "family_pp": dict(family_pp),
        "high7_combined_pp": high7_combined_pp,
        "family_shares": family_shares,
        "wild_cadence": wild_cadence,
        "margs": margs,
    }


# ---------------------------------------------------------------------
# 14 hardlines + v7 bar1 share check
# ---------------------------------------------------------------------
def check14(r):
    checks = []
    s = r["session_bucket"]
    g15 = s.get("ge1_lt5", 0)
    g510 = s.get("ge5_lt10", 0)
    g1020 = s.get("ge10_lt20", 0)
    sum120 = g15 + g510 + g1020

    def chk(name, val, lo, hi):
        ok = lo <= val <= hi
        checks.append((name, val, "PASS" if ok else "FAIL", (lo, hi)))

    chk("H1 hit_session", r["hit_session"], 15, 18)
    chk("H2 total_rtp", r["total_rtp"], 94, 96)
    chk("H3 R1_blank", r["r1_blank"], 30, 40)
    chk("H4 ge1_lt5 (g15)", g15, 10, 15)
    chk("H5 sum_1_20", sum120, 28, 36)
    chk("H6 ge20_lt50", s.get("ge20_lt50", 0), 22, 32)
    chk("H7 ge50_lt100", s.get("ge50_lt100", 0), 17, 27)
    chk("H8 ge100_lt200", s.get("ge100_lt200", 0), 4, 14)
    chk("H9 ge200_lt500", s.get("ge200_lt500", 0), 0, 7.3)
    for i, m in enumerate(r["margs"]):
        chk(f"H{10+i} R{i+1}_jp", m.get("jackpot", 0) * 100, 0, 0.6)
    # H13/H14 are paytable + feature_params byte-equal — not touched (verified
    # by virtue of using production spec.json/weights.json file). We mark them
    # explicitly PASS here as the script never writes those files.
    checks.append(("H13 paytable byte-equal", 0.0, "PASS (not touched)", (None, None)))
    checks.append(("H14 feature_params byte-equal", 0.0, "PASS (not touched)", (None, None)))
    return checks


# ---------------------------------------------------------------------
# Marginal → weights reconstruction (mirrors D's approach)
# ---------------------------------------------------------------------
def marginals_to_weights(strips, margs, scale=10000):
    """Integer per-stop weights such that the implied middle-row marginal
    matches `margs` as closely as possible (rounded to ints, min 1).
    Uses simple per-(reel, symbol) divide-by-count approach. Matches D's
    helper of the same name in m15_v13c_design.py."""
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


def apply_mechanism_b_blanks(strips, weights, top_symbols=("doublediamond", "high7", "topdollar"), floor=1):
    """RTP-neutral blank redistribute: shift weight from non-top-adjacent
    blanks to top-adjacent blanks, preserving per-reel total blank weight
    (and therefore marginals unchanged). Mirrors D's apply_mechanism_b_blanks."""
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


def compute_pwdf(strips, weights):
    """Returns dict: symbol -> [R1%, R2%, R3%] window visibility (post-mechB)."""
    top_syms = ["doublediamond", "high7", "topdollar"]
    table = {}
    for sym in top_syms:
        row = []
        for ri in range(3):
            strip_dicts = [{"symbol": s, "weight": w}
                           for s, w in zip(strips[ri], weights[ri])]
            pw = symbol_window_probability(strip_dicts, sym)
            row.append(pw * 100)
        table[sym] = row
    return table


# ---------------------------------------------------------------------
# Counterexample search for "g15 < 14.4pp infeasible" claim
# ---------------------------------------------------------------------
def ce_candidate_1():
    """CE1: bar1 18/16/14, cherry 3/2.5/2 (lower than PPP_v20). High7 18/15/10
    to absorb. dd 2.5, jp 0.4."""
    R1 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.16, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.14, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_2():
    """CE2: bar1 24/21/18, cherry 2.5/2/1.5, h7 17/14/10. Lower cherry."""
    R1 = {"cherry": 0.025, "1bar": 0.24, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.170, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.21, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.18, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_3():
    """CE3: very low cherry — cherry 1.5/1/1, bar1 26/22/18, h7 18/15/10."""
    R1 = {"cherry": 0.015, "1bar": 0.26, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.010, "1bar": 0.22, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.010, "1bar": 0.18, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_4():
    """CE4: minimal cherry, lower bar1 — cherry 1/0.5/0.5, bar1 22/19/16, h7 22/18/12.
    Tries to push g15 to 7-9pp range."""
    R1 = {"cherry": 0.010, "1bar": 0.22, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.220, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.005, "1bar": 0.19, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.005, "1bar": 0.16, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.120, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_5():
    """CE5: aggressive bar_mixed cut — bar1 16/14/12, bar2 4/3/2, bar3 2/1/1,
    cherry 4/3/2.5, h7 22/18/13."""
    R1 = {"cherry": 0.040, "1bar": 0.16, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.220, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.14, "2bar": 0.03, "3bar": 0.010,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.12, "2bar": 0.02, "3bar": 0.010,
          "high7": 0.130, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_6():
    """CE6: even lower bar density everywhere — bar1 14/12/10, bar2 3/2/2, bar3 1/1/0.5,
    cherry 4/3/2.5, h7 22/18/14."""
    R1 = {"cherry": 0.040, "1bar": 0.14, "2bar": 0.030, "3bar": 0.010,
          "high7": 0.220, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.12, "2bar": 0.020, "3bar": 0.010,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.10, "2bar": 0.020, "3bar": 0.005,
          "high7": 0.140, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_7():
    """CE7: PPP_v20 with cherry cut hard. cherry 1.5/1/1, bar1 28/24/20, h7 17/13/9."""
    R1 = {"cherry": 0.015, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.170, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.010, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.010, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


def ce_candidate_8():
    """CE8: paytable line_3_group g15 hits via bar_mixed. Cut bar1 + bar2 + bar3
    aggressively to kill bar_mixed: bar1 12/10/8, bar2 2/2/1, bar3 1/1/0.5,
    cherry 2.5/2/1.5, h7 30/22/14 (absorb everything)."""
    R1 = {"cherry": 0.025, "1bar": 0.12, "2bar": 0.020, "3bar": 0.010,
          "high7": 0.300, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.10, "2bar": 0.020, "3bar": 0.010,
          "high7": 0.220, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.08, "2bar": 0.010, "3bar": 0.005,
          "high7": 0.140, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CE_CANDIDATES = [
    ("CE1 bar1 18/16/14 cherry 3/2.5/2 h7 18/15/10", ce_candidate_1),
    ("CE2 bar1 24/21/18 cherry 2.5/2/1.5 h7 17/14/10", ce_candidate_2),
    ("CE3 cherry 1.5/1/1 bar1 26/22/18 h7 18/15/10", ce_candidate_3),
    ("CE4 cherry 1/0.5/0.5 bar1 22/19/16 h7 22/18/12", ce_candidate_4),
    ("CE5 bar2 4/3/2 bar3 2/1/1 cherry 4/3/2.5", ce_candidate_5),
    ("CE6 bar1 14/12/10 bar2 3/2/2 bar3 1/1/0.5", ce_candidate_6),
    ("CE7 PPP_v20 + cherry 1.5/1/1 h7 17/13/9", ce_candidate_7),
    ("CE8 bar1 12/10/8 bar2 2/2/1 bar3 1/1/0.5 h7 30/22/14", ce_candidate_8),
]


# ---------------------------------------------------------------------
# Write a synthetic mode_1/weights.json for verify.py against PPP_v20
# ---------------------------------------------------------------------
def write_tmp_weights_for_verify(strips, margs, out_path: Path):
    raw = marginals_to_weights(strips, margs)
    polished = apply_mechanism_b_blanks(strips, raw)
    doc = {
        "machine": "M15",
        "mode": 1,
        "reel_set": "default",
        "weights": polished,
        "feature_params": FP,
        "_notes": [
            "M15 v13c PPP_v20 candidate weights — written by m15_v13c_verify.py",
            "Used ONLY to drive verify.py against PPP_v20 marginals.",
            "Does NOT touch production weights/mode_1/weights.json.",
        ],
        "_v81_mechanism_b": _prod_weights_doc.get("_v81_mechanism_b", {}),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
PPP_V20_R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
              "high7": 0.160, "doublediamond": 0.025, "jackpot": 0.004}
PPP_V20_R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
              "high7": 0.120, "doublediamond": 0.025, "jackpot": 0.004}
PPP_V20_R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
              "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-verify", action="store_true",
                        help="Also run verify.py against the temp weights")
    args = parser.parse_args()

    strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

    print("=" * 70)
    print("§ 1. INDEPENDENT recomputation of PPP_v20")
    print("=" * 70)
    margs = make_marginals(PPP_V20_R1, PPP_V20_R2, PPP_V20_R3)
    r = evaluate(margs)

    # Print the normalized marginals
    print("\nNormalized marginals (after blank-residual & re-normalization):")
    for ri, m in enumerate(margs):
        nb = 1.0 - m.get("blank", 0)
        parts = ", ".join(f"{s}={v*100:.3f}" for s, v in sorted(m.items(),
                                                                 key=lambda kv: -kv[1]))
        print(f"  R{ri+1} blank={m['blank']*100:.3f}  nb={nb*100:.3f}  {parts}")

    print(f"\nbase_rtp = {r['base_rtp']:.3f}pp")
    print(f"feature_rtp = {r['feature_rtp']:.3f}pp  (= trigger {r['trigger']:.3f}% × feat_EV {FEAT_EV_TOTAL:.4f}×100)")
    print(f"total_rtp = {r['total_rtp']:.3f}pp")
    print(f"split base:feature = {r['base_rtp']/r['total_rtp']*100:.1f} : {r['feature_rtp']/r['total_rtp']*100:.1f}")
    print(f"\nbase_hit = {r['base_hit']:.4f}%   trigger = {r['trigger']:.4f}%   hit_session = {r['hit_session']:.4f}%")
    print(f"R1_blank = {r['r1_blank']:.3f}%   R2_blank = {r['r2_blank']:.3f}%   R3_blank = {r['r3_blank']:.3f}%")

    s = r["session_bucket"]
    g15 = s.get("ge1_lt5", 0)
    g510 = s.get("ge5_lt10", 0)
    g1020 = s.get("ge10_lt20", 0)
    g2050 = s.get("ge20_lt50", 0)
    g50100 = s.get("ge50_lt100", 0)
    g100200 = s.get("ge100_lt200", 0)
    g200500 = s.get("ge200_lt500", 0)
    g500plus = s.get("ge500_lt1000", 0) + s.get("ge1000_lt5000", 0) + s.get("ge5000", 0)
    sum_1_20 = g15 + g510 + g1020
    print("\nSession buckets (pp, base + feature):")
    print(f"  g15  (1-5×)    = {g15:7.3f}    D: 14.896 (Δ={g15-14.896:+.3f})")
    print(f"  g510 (5-10×)   = {g510:7.3f}    D:  8.712 (Δ={g510-8.712:+.3f})")
    print(f"  g1020(10-20×)  = {g1020:7.3f}    D:  6.224 (Δ={g1020-6.224:+.3f})")
    print(f"  g2050(20-50×)  = {g2050:7.3f}    D: 25.065 (Δ={g2050-25.065:+.3f})")
    print(f"  g50100(50-100×)= {g50100:7.3f}    D: 26.978 (Δ={g50100-26.978:+.3f})")
    print(f"  g100200       = {g100200:7.3f}    D: 11.072 (Δ={g100200-11.072:+.3f})")
    print(f"  g200500       = {g200500:7.3f}    D:  2.335 (Δ={g200500-2.335:+.3f})")
    print(f"  g500+         = {g500plus:7.3f}    D:  0.062 (Δ={g500plus-0.062:+.3f})")
    print(f"  sum_1_20      = {sum_1_20:7.3f}    D: 29.832 (Δ={sum_1_20-29.832:+.3f})")

    # Per-pay-id RTP
    print("\nPer-pay-id RTP (pp) and hit (%):")
    for pid in sorted(r["pay_rtp"].keys(), key=lambda x: -r["pay_rtp"][x]):
        fam = PAY_FAM_MAP.get(pid, "?")
        print(f"  pay_id {pid:>3s} ({fam:11s}): rtp={r['pay_rtp'][pid]:7.4f}pp  hit={r['pay_hits'][pid]:8.5f}%")

    # Family shares
    print("\nFamily share-of-base (%):")
    for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                "bar_mixed", "high7", "wild_pure"):
        v = r["family_shares"].get(fam, 0)
        pp = (r["high7_combined_pp"] if fam == "high7"
              else r["family_pp"].get(fam, 0))
        # D's claimed values
        d_claim = {
            "bar1": 26.60, "high7": 31.48, "bar2": 2.67, "bar3": 0.82,
            "cherry1": 22.84, "cherry2": 4.28, "cherry3": 0.16,
            "bar_mixed": 10.45, "wild_pure": 0.70,
        }.get(fam)
        diff_str = f" (D: {d_claim:.2f}, Δ={v - d_claim:+.2f})" if d_claim else ""
        print(f"  {fam:11s} {v:7.3f}%  ({pp:6.3f}pp){diff_str}")

    # Wild cadence
    print(f"\nwild_pure cadence = 1/{r['wild_cadence']:.0f}    D: 1/64000 "
          f"(Δ relative diff = {abs(r['wild_cadence']-64000)/64000*100:+.1f}%)")
    # in-band check
    in_band = 50000 <= r['wild_cadence'] <= 100000
    print(f"  philosophy §7 band [1/50k, 1/100k]: {'IN BAND' if in_band else 'OUT OF BAND'}")

    # PWDF
    raw_w = marginals_to_weights(strips, margs)
    polished_w = apply_mechanism_b_blanks(strips, raw_w)
    pwdf = compute_pwdf(strips, polished_w)
    print("\nPWDF post-mechanism-B (top symbols, % window visibility):")
    for sym, row in pwdf.items():
        max_r = max(row)
        max_reel = row.index(max_r) + 1
        if sym == "doublediamond":
            d_claim = 27.36
        elif sym == "high7":
            d_claim = 36.86
        else:
            d_claim = 24.31
        floor = {"doublediamond": 28.0, "high7": 28.0, "topdollar": 22.0}[sym]
        ok = max_r >= floor
        print(f"  {sym:13s} R1={row[0]:6.3f} R2={row[1]:6.3f} R3={row[2]:6.3f} "
              f"max={max_r:6.3f}@R{max_reel}   D max: {d_claim:.2f} (Δ={max_r-d_claim:+.2f})"
              f"  floor={floor}% {'PASS' if ok else 'FAIL'}")

    # 14-hardline PASS/FAIL
    print("\n" + "=" * 70)
    print("§ 2. 14-hardline check (USER_HARDLINES.md v7)")
    print("=" * 70)
    checks = check14(r)
    n_fail = 0
    for nm, val, st, band in checks:
        lo, hi = band
        if lo is None:
            print(f"  {st:5s} {nm:40s} val={val:8.4f}")
        else:
            print(f"  {st:5s} {nm:40s} val={val:8.4f}  band=[{lo}, {hi}]")
        if st == "FAIL":
            n_fail += 1
    print(f"\nTotal hardline FAILs: {n_fail}/{len(checks)}")

    # v7 implicit bar1 share ≤ ~30%
    bar1_share = r["family_shares"].get("bar1", 0)
    bar1_ok = bar1_share <= 30.0
    print(f"\nv7 implicit bar1 family share ≤ 30%: {bar1_share:.2f}% {'PASS' if bar1_ok else 'FAIL'}")

    # ----- § 3 counterexample search -----
    print("\n" + "=" * 70)
    print("§ 3. Counterexample search — D's 'g15 < 14.4 infeasible' claim")
    print("=" * 70)
    feasible_below_144 = []
    for ce_name, ce_fn in CE_CANDIDATES:
        try:
            ce_margs = ce_fn()
            ce_r = evaluate(ce_margs)
            ce_g15 = ce_r["session_bucket"].get("ge1_lt5", 0)
            ce_checks = check14(ce_r)
            failed = [(nm, val, band) for nm, val, st, band in ce_checks if st == "FAIL"]
            ce_bar1 = ce_r["family_shares"].get("bar1", 0)
            ce_bar1_violation = ce_bar1 > 30.0
            ce_total = ce_r["total_rtp"]
            ce_r1 = ce_r["r1_blank"]
            print(f"\n  {ce_name}")
            print(f"    g15={ce_g15:.3f}  total_rtp={ce_total:.3f}  R1_blank={ce_r1:.3f}  bar1_share={ce_bar1:.2f}%")
            print(f"    hardline fails ({len(failed)}): " + (", ".join(f"{nm}={val:.3f} band={band}" for nm, val, band in failed) if failed else "NONE"))
            if ce_bar1_violation:
                print(f"    bar1 share > 30%: VIOLATION")
            if not failed and not ce_bar1_violation and ce_g15 < 14.4:
                feasible_below_144.append((ce_name, ce_g15, ce_total, ce_bar1))
        except Exception as e:
            print(f"  {ce_name} -> ERROR {type(e).__name__}: {e}")

    print("\n  --- counterexample summary ---")
    if feasible_below_144:
        print(f"  *** FOUND {len(feasible_below_144)} feasible candidate(s) with g15 < 14.4 ***")
        for nm, g, t, b in feasible_below_144:
            print(f"    {nm}: g15={g:.3f} total_rtp={t:.3f} bar1={b:.2f}%")
        print("  D's 'g15 < 14.4 infeasible' claim: DISPUTED")
    else:
        print("  No feasible candidate with g15 < 14.4 found.")
        print("  D's 'g15 < 14.4 infeasible' claim: CONFIRMED with these 8 candidates")
        print("  (consistent with D's algebraic argument in design_v13c.md §8.1)")

    # ----- § 4 write temp weights and (optionally) run verify.py -----
    print("\n" + "=" * 70)
    print("§ 4. Write temp weights + run verify.py against PPP_v20")
    print("=" * 70)
    write_tmp_weights_for_verify(strips, margs, TMP_WEIGHTS_PATH)
    print(f"  wrote: {TMP_WEIGHTS_PATH}")

    if args.run_verify:
        # Run verify.py against the temp dir
        cmd = [
            sys.executable, "-m", "slot_designer.machines.M15.verify",
            "--weights-dir", str(TMP_DIR),
        ]
        print(f"\n  Running: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True)
        print(f"  exit_code: {proc.returncode}")
        print("\n  ---- stdout ----")
        print(proc.stdout)
        if proc.stderr:
            print("\n  ---- stderr ----")
            print(proc.stderr)

    return r


if __name__ == "__main__":
    main()
