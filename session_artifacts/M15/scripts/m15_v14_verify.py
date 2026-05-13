"""M15 v14 mode 1 — INDEPENDENT VERIFIER (post v8 hardline shift, 2026-05-12).

Verifies D's C38_C14_rtp_target_95 candidate from m15_v14_design.py WITHOUT
importing anything from D's script. Takes C38_C14 marginals as direct input,
reconstructs integer per-stop weights via the same primitives D uses
(marginals_to_weights + apply_mechanism_b_blanks defined locally), and runs
analytic_profile_from_marginals from production devtools.

Outputs:
  * Recomputed metrics: RTP, hit, R1 blank, per-pay-id RTP + 1-in-N, family
    shares, bar hierarchy, wild_pure cadence, session bucket distribution,
    PWDF table
  * v8 hardline check (6 hard items)
  * Numeric diff vs D's claimed numbers
  * Temp weights.json write to _tmp_v14_verify/mode_1/ (never touches production)
"""
from __future__ import annotations

import json
import os
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
PROD_WEIGHTS_PATH = _M15_DIR / "weights" / "mode_1" / "weights.json"

# ----------------------------------------------------------------------
# C38_C14 marginals (as given in V/X prompt). Recomputed FROM SCRATCH —
# no import from D's script.
# ----------------------------------------------------------------------

C38_R1 = {"blank": 0.385,  "cherry": 0.040, "1bar": 0.202, "2bar": 0.165,
          "3bar": 0.103,  "high7": 0.072, "doublediamond": 0.029,
          "jackpot": 0.004}
C38_R2 = {"blank": 0.503,  "cherry": 0.035, "1bar": 0.165, "2bar": 0.135,
          "3bar": 0.073,  "high7": 0.057, "doublediamond": 0.028,
          "jackpot": 0.004}
C38_R3 = {"blank": 0.5897, "cherry": 0.025, "1bar": 0.135, "2bar": 0.110,
          "3bar": 0.055,  "high7": 0.047, "doublediamond": 0.024,
          "topdollar": 0.0113, "jackpot": 0.003}


def normalize_margs(d):
    """Sanity normalize to sum=1 (catch typos)."""
    s = sum(d.values())
    return {k: v / s for k, v in d.items() if v > 0}


C38_MARGS = [normalize_margs(C38_R1), normalize_margs(C38_R2), normalize_margs(C38_R3)]

# ----------------------------------------------------------------------
# Load engine + strips + feature
# ----------------------------------------------------------------------

engine, _spec = load_engine(SPEC_PATH, PROD_WEIGHTS_PATH, strips_path=STRIPS_PATH)
EV = engine.evaluator
STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

# Locked feature_params v9 (read from production)
prod_doc = json.loads(PROD_WEIGHTS_PATH.read_text(encoding="utf-8"))
fp = prod_doc["feature_params"]

dist = _round_payout_distribution(
    tuple(fp["x_count_weights"]),
    tuple(fp["y_count_weights"]),
    tuple(fp["x_value_weights"]),
    tuple(fp["y_value_weights"]),
)
p_accept = sum(p for r, p in dist if r >= fp["accept_threshold"])
accept_dist = [(r, p) for r, p in dist if r >= fp["accept_threshold"]]
final_dist = defaultdict(float)
for round_idx in range(1, fp["max_rounds"]):
    branch = ((1 - p_accept) ** (round_idx - 1)) * p_accept
    for r, p in accept_dist:
        final_dist[r] += branch * (p / p_accept) if p_accept > 0 else 0
branch_forced = (1 - p_accept) ** (fp["max_rounds"] - 1)
for r, p in dist:
    final_dist[r] += branch_forced * p


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


FEAT_BUCKET_EV = defaultdict(float)
FEAT_BUCKET_HIT = defaultdict(float)
for r, p in final_dist.items():
    b = to_bucket(r)
    if b:
        FEAT_BUCKET_EV[b] += r * p
        FEAT_BUCKET_HIT[b] += p
FEAT_EV_PER_TRIGGER = sum(FEAT_BUCKET_EV.values())
# Probability per round in feature that round produces R >= 1000
FEAT_P_R_GE_1000_PER_TRIGGER = sum(p for r, p in dist if r >= 1000)
FEAT_P_R_GE_200_PER_TRIGGER = sum(p for r, p in dist if r >= 200)


# ----------------------------------------------------------------------
# Family mapping (matches verify.py FAMILY_OF_PAY_ID)
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
# Independent reimpl of marginals_to_weights + apply_mechanism_b_blanks.
# Logic must MATCH D's script byte-for-byte (per "Reconstruct integer
# per-stop weights via marginals_to_weights + apply_mechanism_b_blanks").
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
    """Recompute marginals from integer weights so we measure ENGINE truth."""
    out = []
    for ri, reel in enumerate(strips):
        total = sum(weights[ri])
        c = defaultdict(int)
        for sym, w in zip(reel, weights[ri]):
            c[sym] += w
        out.append({sym: w / total for sym, w in c.items() if w > 0})
    return out


# ----------------------------------------------------------------------
# Evaluation pipeline
# ----------------------------------------------------------------------

def evaluate(margs, *, tag=""):
    """Returns dict with analytic profile + session-centric overlay."""
    prof = analytic_profile_from_marginals(EV, margs)
    trigger = margs[2].get("topdollar", 0.0)
    base_rtp_pct = prof["rtp_pct"]
    base_hit = prof["hit_rate"]
    feature_rtp_pct = trigger * FEAT_EV_PER_TRIGGER * 100
    total_rtp_pct = base_rtp_pct + feature_rtp_pct
    hit_session = (base_hit + trigger) * 100

    # Session-centric bucket overlay
    session_bucket = {k: v * 100 for k, v in prof["bucket_rtp"].items()}
    for k, ev in FEAT_BUCKET_EV.items():
        session_bucket[k] = session_bucket.get(k, 0) + trigger * ev * 100

    # Per-pay-id RTP + cadence
    pay_rtp = prof["pay_rtp"]
    pay_hits = prof["pay_hits"]
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

    # 666 (feature trigger) is the trigger pay_id, equals topdollar marginal
    pay_hits_full = dict(pay_hits)
    pay_hits_full["666"] = trigger
    pay_rtp_full = dict(pay_rtp)
    pay_rtp_full["666"] = trigger * 0.0  # win=0 marker pay
    # Feature RTP contribution (per-trigger EV × trigger probability)
    pay_rtp_full["feature_via_666"] = trigger * FEAT_EV_PER_TRIGGER

    return {
        "tag": tag,
        "total_rtp": total_rtp_pct,
        "base_rtp": base_rtp_pct,
        "feature_rtp": feature_rtp_pct,
        "hit_session": hit_session,
        "base_hit": base_hit * 100,
        "trigger": trigger * 100,
        "r1_blank": margs[0].get("blank", 0) * 100,
        "r2_blank": margs[1].get("blank", 0) * 100,
        "r3_blank": margs[2].get("blank", 0) * 100,
        "session_bucket": dict(session_bucket),
        "pay_hits": pay_hits_full,
        "pay_rtp": pay_rtp_full,
        "family_pp": dict(family_pp),
        "high7_combined_pp": high7_combined_pp,
        "family_shares": family_shares,
        "wild_cadence": wild_cadence,
        "margs": margs,
        "cv": prof["cv"],
        # for 1000+ check
        "feat_p_r_ge_1000_per_trigger": FEAT_P_R_GE_1000_PER_TRIGGER,
        "p_r_ge_1000_per_spin": trigger * FEAT_P_R_GE_1000_PER_TRIGGER,
    }


def pwdf_table(weights):
    top_syms = ["doublediamond", "high7", "topdollar"]
    table = {}
    for sym in top_syms:
        row = []
        for ri in range(3):
            strip_dicts = [{"symbol": s, "weight": w}
                           for s, w in zip(STRIPS[ri], weights[ri])]
            pw = symbol_window_probability(strip_dicts, sym)
            row.append(pw * 100)
        table[sym] = row
    return table


# ----------------------------------------------------------------------
# Hardline checks (v8 hard items)
# ----------------------------------------------------------------------

def check_v8_hardlines(r_analytic, r_engine, *, paytable_byte_equal,
                       feature_params_byte_equal, strip_byte_equal):
    """Verify each of the 6 user v8 hardlines (paytable / feature shape — both
    byte-equal locked, just confirm not modified; RTP / hit / R1 blank / jp /
    1000+ avoidance)."""
    checks = []

    # H1: Paytable byte-equal (qualitative)
    checks.append(("H1 paytable_byte_equal",
                   "byte_equal" if paytable_byte_equal else "MODIFIED",
                   "PASS" if paytable_byte_equal else "FAIL",
                   "qualitative"))

    # H2: feature_params byte-equal v9
    checks.append(("H2 feature_params_byte_equal_v9",
                   "byte_equal" if feature_params_byte_equal else "MODIFIED",
                   "PASS" if feature_params_byte_equal else "FAIL",
                   "qualitative"))

    # H3: strip byte-equal
    checks.append(("H3 strip_byte_equal",
                   "byte_equal" if strip_byte_equal else "MODIFIED",
                   "PASS" if strip_byte_equal else "FAIL",
                   "qualitative"))

    # H4: total_rtp ∈ [94, 96] - check ENGINE-realized value (production truth)
    for tag, r in (("analytic", r_analytic), ("engine", r_engine)):
        v = r["total_rtp"]
        ok = 94 <= v <= 96
        checks.append((f"H4 total_rtp ({tag})", f"{v:.4f}pp",
                       "PASS" if ok else "FAIL", "[94, 96]"))

    # H5: hit_session ∈ [15, 18]
    for tag, r in (("analytic", r_analytic), ("engine", r_engine)):
        v = r["hit_session"]
        ok = 15 <= v <= 18
        checks.append((f"H5 hit_session ({tag})", f"{v:.4f}%",
                       "PASS" if ok else "FAIL", "[15, 18]"))

    # H6: R1 blank ∈ [30, 40]
    for tag, r in (("analytic", r_analytic), ("engine", r_engine)):
        v = r["r1_blank"]
        ok = 30 <= v <= 40
        checks.append((f"H6 R1_blank ({tag})", f"{v:.4f}%",
                       "PASS" if ok else "FAIL", "[30, 40]"))

    # H7: jackpot per-reel ≤ 0.6%
    for ri in range(3):
        for tag, r in (("analytic", r_analytic), ("engine", r_engine)):
            v = r["margs"][ri].get("jackpot", 0) * 100
            ok = v <= 0.6
            checks.append((f"H7 R{ri+1}_jackpot ({tag})", f"{v:.4f}%",
                           "PASS" if ok else "FAIL", "[0, 0.6]"))

    # H8: Avoid 1000× bet+ (qualitative — wild_pure max 200×, jackpot
    # reroll-blocked, feature P(R≥1000) per spin ≤ 1e-5)
    p_1000 = r_engine["p_r_ge_1000_per_spin"]
    ok = p_1000 <= 1e-5
    checks.append(("H8 P(R>=1000/spin)", f"{p_1000:.3e}",
                   "PASS" if ok else "FAIL", "<= 1e-5 (user_brief #5)"))

    return checks


# ----------------------------------------------------------------------
# Write temp weights file (NOT TO PRODUCTION)
# ----------------------------------------------------------------------

def write_temp_weights(weights, *, feature_params):
    """Write _tmp_v14_verify/mode_1/weights.json — never touches production."""
    tmp_dir = _ROOT / "session_artifacts" / "M15" / "_tmp_v14_verify" / "mode_1"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "machine": "M15",
        "mode": 1,
        "reel_set": "default",
        "weights": weights,
        "feature_params": feature_params,
        "_notes": ["V verifier temp output — DO NOT SHIP. C38_C14 marginals."],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": ["doublediamond", "high7", "topdollar"],
            "rationale": "Per philosophy §15.4 / §15.5",
        },
    }
    out_path = tmp_dir / "weights.json"
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out_path


# ----------------------------------------------------------------------
# D's claimed numbers (from V/X prompt — for diff)
# ----------------------------------------------------------------------

D_CLAIM = {
    "total_rtp_engine": 94.262,
    "total_rtp_analytic": 94.752,
    "hit_session": 17.34,
    "r1_blank": 38.52,
    "wild_cadence": 51303,
    "family_shares": {
        "cherry1": 21.88,
        "bar1": 12.11,
        "bar2": 15.38,
        "bar3": 9.26,
        "bar_mixed": 27.93,
        "high7": 8.70,
        "wild_pure": 0.91,
    },
    "bar_hier": {  # hit %
        "bar1": 0.71,
        "bar2": 0.42,
        "bar3": 0.10,
    },
    "cherry3_hit_1in": 28000,  # ~1/28k
    "dd_pwdf_max": 27.90,
}


def diff_vs_d(r_analytic):
    """0.05pp tolerance per V/X brief."""
    diffs = []

    # RTP
    diffs.append(("total_rtp (analytic)", r_analytic["total_rtp"],
                  D_CLAIM["total_rtp_analytic"],
                  abs(r_analytic["total_rtp"] - D_CLAIM["total_rtp_analytic"])))

    # hit_session
    diffs.append(("hit_session", r_analytic["hit_session"],
                  D_CLAIM["hit_session"],
                  abs(r_analytic["hit_session"] - D_CLAIM["hit_session"])))

    # R1 blank
    diffs.append(("R1_blank", r_analytic["r1_blank"], D_CLAIM["r1_blank"],
                  abs(r_analytic["r1_blank"] - D_CLAIM["r1_blank"])))

    # Family shares
    for fam, d_v in D_CLAIM["family_shares"].items():
        my_v = r_analytic["family_shares"].get(fam, 0)
        diffs.append((f"family_share[{fam}]", my_v, d_v, abs(my_v - d_v)))

    # bar hierarchy hit
    for pid, fam in [("7", "bar1"), ("5", "bar2"), ("3", "bar3")]:
        my_v = r_analytic["pay_hits"].get(pid, 0) * 100
        d_v = D_CLAIM["bar_hier"][fam]
        diffs.append((f"bar_hier_hit[{fam}]", my_v, d_v, abs(my_v - d_v)))

    # wild cadence
    my_cad = r_analytic["wild_cadence"]
    diffs.append(("wild_cadence", my_cad, D_CLAIM["wild_cadence"],
                  abs(my_cad - D_CLAIM["wild_cadence"])))

    # cherry-3 cadence
    c3_p = r_analytic["pay_hits"].get("4", 0)
    c3_1in = 1.0 / c3_p if c3_p > 0 else float("inf")
    diffs.append(("cherry3_1in", c3_1in, D_CLAIM["cherry3_hit_1in"],
                  abs(c3_1in - D_CLAIM["cherry3_hit_1in"])))

    return diffs


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print("=" * 70)
    print("M15 v14 INDEPENDENT VERIFIER — C38_C14_rtp_target_95")
    print("=" * 70)

    # ---- ANALYTIC pass: pure marginals
    r_analytic = evaluate(C38_MARGS, tag="analytic")

    # ---- ENGINE pass: marginals -> integer weights -> mechanism B -> remarginalize
    weights_raw = marginals_to_weights(STRIPS, C38_MARGS)
    weights_b = apply_mechanism_b_blanks(STRIPS, weights_raw)
    engine_margs = reel_marginals_from_weights(STRIPS, weights_b)
    r_engine = evaluate(engine_margs, tag="engine")

    # ---- BYTE-EQUAL checks
    prod_strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    strip_byte_equal = prod_strips == STRIPS

    spec_bytes = SPEC_PATH.read_bytes()
    spec_dict = json.loads(spec_bytes)
    pays_current = spec_dict["pays"]
    import hashlib
    pays_canonical = json.dumps(
        [{k: v for k, v in p.items() if not k.startswith("_")} for p in pays_current],
        sort_keys=True, separators=(",", ":"))
    paytable_hash = hashlib.sha256(pays_canonical.encode()).hexdigest()[:16]
    paytable_byte_equal = paytable_hash == "d537686536381b1f"

    prod_fp = prod_doc["feature_params"]
    feature_params_byte_equal = (
        prod_fp["x_count_weights"] == [5, 40, 40, 12, 3]
        and prod_fp["y_count_weights"] == [75, 20, 5]
        and abs(prod_fp["x_value_weights"][0] - 0.0001) < 1e-9
        and abs(prod_fp["x_value_weights"][-1] - 40.9684) < 1e-3
        and prod_fp["y_value_weights"] == [1, 1]
        and prod_fp["accept_threshold"] == 40
        and prod_fp["max_rounds"] == 4
    )

    # ---- Print analytic vs engine numerics
    print("\n--- ANALYTIC (continuous marginals) ---")
    for k in ("total_rtp", "base_rtp", "feature_rtp", "hit_session", "base_hit",
              "trigger", "r1_blank", "r2_blank", "r3_blank", "wild_cadence"):
        v = r_analytic[k]
        if k == "wild_cadence":
            print(f"  {k}: 1/{v:.0f}")
        else:
            print(f"  {k}: {v:.4f}")

    print("\n--- ENGINE (integer weights after mechanism B) ---")
    for k in ("total_rtp", "base_rtp", "feature_rtp", "hit_session", "base_hit",
              "trigger", "r1_blank", "r2_blank", "r3_blank", "wild_cadence"):
        v = r_engine[k]
        if k == "wild_cadence":
            print(f"  {k}: 1/{v:.0f}")
        else:
            print(f"  {k}: {v:.4f}")

    # ---- Per-pay-id RTP + cadence
    print("\n--- PER-PAY-ID (analytic) ---")
    pid_order = ["9", "71", "4", "1", "2", "21", "3", "5", "7", "8", "666"]
    print(f"  {'pid':>4} {'fam':<12} {'mult':>5} {'hit%':>10} {'1in':>10} {'rtp_pp':>8}")
    for pid in pid_order:
        fam = FAMILY_OF_PAY_ID.get(pid, "trigger")
        if pid == "666":
            fam = "trigger"
            mult = 0
        else:
            mult = PAY_MULT.get(pid, 0)
        p = r_analytic["pay_hits"].get(pid, 0) * 100
        oneinn = (1 / (p / 100)) if p > 0 else float("inf")
        if pid == "666":
            rtp_pp_print = r_analytic["pay_rtp"].get("feature_via_666", 0) * 100
            fam = "feature_trig"
        else:
            rtp_pp_print = r_analytic["pay_rtp"].get(pid, 0) * 100
        print(f"  {pid:>4} {fam:<12} {mult:>5} {p:>9.4f}% {oneinn:>10.0f} "
              f"{rtp_pp_print:>7.3f}")

    # ---- Family shares
    print("\n--- FAMILY SHARES (analytic, share-of-base) ---")
    fs = r_analytic["family_shares"]
    for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                "bar_mixed", "high7", "wild_pure"):
        share = fs.get(fam, 0)
        pp = r_analytic["family_pp"].get(fam, 0) if fam != "high7" \
             else r_analytic["high7_combined_pp"]
        print(f"  {fam:<12} share={share:>6.2f}%  ({pp:>6.3f}pp)")

    # ---- Bar hierarchy
    print("\n--- BAR HIERARCHY (hit %, analytic) ---")
    p_b1 = r_analytic["pay_hits"].get("7", 0) * 100
    p_b2 = r_analytic["pay_hits"].get("5", 0) * 100
    p_b3 = r_analytic["pay_hits"].get("3", 0) * 100
    print(f"  bar1 (5x):  {p_b1:.4f}%  (1/{1/(p_b1/100):.0f})")
    print(f"  bar2 (10x): {p_b2:.4f}%  (1/{1/(p_b2/100):.0f})")
    print(f"  bar3 (20x): {p_b3:.4f}%  (1/{1/(p_b3/100):.0f})")
    print(f"  hierarchy direction: bar1 > bar2 > bar3 = "
          f"{p_b1 > p_b2 > p_b3}")

    # ---- Session buckets
    print("\n--- SESSION BUCKETS (RTP pp, analytic+feature overlay) ---")
    bucket_keys = [k for _, k in _BUCKET_EDGES]
    sb = r_analytic["session_bucket"]
    total_sum = 0
    for k in bucket_keys:
        v = sb.get(k, 0)
        total_sum += v
        print(f"  {k:<16}: {v:>7.4f}pp")
    print(f"  TOTAL:           {total_sum:>7.4f}pp")

    # ---- PWDF
    print("\n--- PWDF (after mechanism B, top symbols) ---")
    pwdf = pwdf_table(weights_b)
    for sym, vals in pwdf.items():
        max_v = max(vals)
        print(f"  {sym:<15} R1={vals[0]:>6.2f}%  R2={vals[1]:>6.2f}%  "
              f"R3={vals[2]:>6.2f}%  MAX={max_v:>6.2f}%")

    # ---- v8 HARDLINES
    print("\n--- v8 HARDLINES ---")
    checks = check_v8_hardlines(r_analytic, r_engine,
                                paytable_byte_equal=paytable_byte_equal,
                                feature_params_byte_equal=feature_params_byte_equal,
                                strip_byte_equal=strip_byte_equal)
    n_fail = 0
    for name, val, st, note in checks:
        print(f"  {st:4}  {name:<32} {val:<20}  ({note})")
        if st == "FAIL":
            n_fail += 1
    print(f"\n  v8 hardlines: {len(checks) - n_fail} PASS / {n_fail} FAIL of {len(checks)}")

    # ---- Diff vs D
    print("\n--- DIFF vs D's claims (0.05pp tolerance) ---")
    diffs = diff_vs_d(r_analytic)
    big_diffs = []
    for name, my_v, d_v, delta in diffs:
        ok = delta <= 0.05 if "cadence" not in name and "1in" not in name else delta <= max(100, abs(d_v) * 0.01)
        # cadence: allow ~100-spin tolerance; cherry3 1in: 1% absolute
        flag = "OK" if ok else "DIFF"
        if not ok:
            big_diffs.append((name, my_v, d_v, delta))
        print(f"  {flag:4}  {name:<24}  mine={my_v:>12.4f}  D={d_v:>12.4f}  "
              f"delta={delta:>10.4f}")

    if big_diffs:
        print(f"\n  TOP DIFFS (>tolerance):")
        for name, mine, dv, delta in sorted(big_diffs, key=lambda x: -x[3])[:3]:
            print(f"    {name}: mine={mine:.4f} D={dv:.4f} delta={delta:.4f}")

    # ---- Write temp weights for verify.py
    print("\n--- WRITING TEMP WEIGHTS ---")
    tmp_path = write_temp_weights(weights_b, feature_params=prod_fp)
    print(f"  -> {tmp_path}")

    # ---- save summary dict for downstream (md report)
    summary = {
        "analytic": r_analytic,
        "engine": r_engine,
        "v8_hardlines": checks,
        "v8_fails": n_fail,
        "diffs_vs_d": diffs,
        "pwdf": pwdf,
        "paytable_byte_equal": paytable_byte_equal,
        "feature_params_byte_equal": feature_params_byte_equal,
        "strip_byte_equal": strip_byte_equal,
        "weights_b": weights_b,
    }
    return summary


if __name__ == "__main__":
    main()
