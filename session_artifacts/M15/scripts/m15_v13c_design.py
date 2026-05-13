"""M15 v13c mode 1 — Designer candidate generator under USER_HARDLINES.md v7.

v7 changes vs v6 (2026-05-12):
  - DROPPED: "g15 NOT max(g15, g510, g1020)" direction
  - ADDED:   "g15 as low as possible within [10, 15] (target lower end 10)"
  - ADDED:   "bar1 family share-of-base ≤ ~30%" (implicit from user "not bar1 dominant")

Strategy:
  - cherry ~4-5% on R1, lower on R2/R3 (cherry-1 anchors low g15 ~7-9pp)
  - bar1 ~16-22% on R1, lower on R2/R3 (bar1 family ~25-30% share)
  - bar2 ~10-14% per reel (substantially higher than v13b's 4.5%)
  - bar3 ~4-6% per reel (substantially higher than v13b's 1.2%)
  - high7 ~13-18% per reel (mid-pay engine)
  - dd 2.5-2.8% (wild cadence)
  - jp ≤ 0.5
  - td R3 = 0.011 (locked feature trigger)

R1 non-blank target ~60-65% so R1 blank ~35-40% (in [30,40]).
R2/R3 follow R1 ≤ R3 blank winners-friendly.

Verify.py NOT modified. USER_HARDLINES.md NOT modified.
No production weights written.
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
WEIGHTS_PATH = _M15_DIR / "weights" / "mode_1" / "weights.json"

# load engine ONCE (we don't mutate weights — just borrow evaluator)
engine, _spec = load_engine(SPEC_PATH, WEIGHTS_PATH, strips_path=STRIPS_PATH)
EV = engine.evaluator

# Load feature_params (LOCKED v9, byte-equal)
fp = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))["feature_params"]

# Precompute feature per-bucket EV
dist = _round_payout_distribution(
    tuple(fp["x_count_weights"]),
    tuple(fp["y_count_weights"]),
    tuple(fp["x_value_weights"]),
    tuple(fp["y_value_weights"]),
)
p_accept = sum(p for r, p in dist if r >= fp["accept_threshold"])
accept_dist = [(r, p) for r, p in dist if r >= fp["accept_threshold"]]
final = defaultdict(float)
for round_idx in range(1, fp["max_rounds"]):
    branch = ((1 - p_accept) ** (round_idx - 1)) * p_accept
    for r, p in accept_dist:
        final[r] += branch * (p / p_accept) if p_accept > 0 else 0
branch_forced = (1 - p_accept) ** (fp["max_rounds"] - 1)
for r, p in dist:
    final[r] += branch_forced * p

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
for r, p in final.items():
    b = to_bucket(r)
    if b:
        FEAT_BUCKET_EV[b] += r * p
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


def make_marginals(R1, R2, R3):
    out = []
    for R in (R1, R2, R3):
        R = dict(R)
        non_blank = sum(R.values())
        R["blank"] = max(0.001, 1.0 - non_blank)
        s = sum(R.values())
        out.append({k: v / s for k, v in R.items() if v > 0})
    return out


def evaluate(margs):
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

    pay_rtp = prof["pay_rtp"]
    family_pp = defaultdict(float)
    for pid, rtp in pay_rtp.items():
        fam = PAY_FAM_MAP.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp * 100
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
        "pay_hits": prof["pay_hits"],
        "pay_rtp": pay_rtp,
        "family_pp": dict(family_pp),
        "high7_combined_pp": high7_combined_pp,
        "family_shares": family_shares,
        "wild_cadence": wild_cadence,
        "margs": margs,
    }


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
    chk("H4 ge1_lt5", g15, 10, 15)
    chk("H5 sum_1_20", sum120, 28, 36)
    chk("H6 ge20_lt50", s.get("ge20_lt50", 0), 22, 32)
    chk("H7 ge50_lt100", s.get("ge50_lt100", 0), 17, 27)
    chk("H8 ge100_lt200", s.get("ge100_lt200", 0), 4, 14)
    chk("H9 ge200_lt500", s.get("ge200_lt500", 0), 0, 7.3)
    for i, m in enumerate(r["margs"]):
        chk(f"H{10+i} R{i+1}_jp", m.get("jackpot", 0) * 100, 0, 0.6)
    return checks


def apply_mechanism_b_blanks(strips, weights, top_symbols=("doublediamond", "high7", "topdollar"), floor=1):
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


def pwdf_table(margs, strips):
    weights_raw = marginals_to_weights(strips, margs)
    weights = apply_mechanism_b_blanks(strips, weights_raw)
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


def report(name, r, strips=None, verbose=True):
    checks = check14(r)
    n_fail = sum(1 for _, _, st, _ in checks if st == "FAIL")
    fs = r["family_shares"]

    bar1_share = fs.get("bar1", 0)
    bar1_ok = bar1_share <= 30.0

    KEY_FAMILIES = ["cherry1", "bar1", "bar2", "bar3", "bar_mixed", "high7"]
    family_violations = []
    for fam in KEY_FAMILIES:
        v = fs.get(fam, 0)
        if v < 5.0:
            family_violations.append((fam, v, "below 5%"))
        elif v > 30.0:
            family_violations.append((fam, v, "above 30%"))

    cadence_ok = 50000 <= r["wild_cadence"] <= 100000
    rtp_safe = r["total_rtp"] >= 94.3

    g15 = r["session_bucket"].get("ge1_lt5", 0)
    g15_low = g15 <= 13.0

    if verbose:
        print(f"\n======== Candidate: {name} ========")
        print(f"  total_rtp={r['total_rtp']:.3f}pp  hit_session={r['hit_session']:.3f}%")
        split_b = r['base_rtp']/r['total_rtp']*100 if r['total_rtp'] > 0 else 0
        split_f = r['feature_rtp']/r['total_rtp']*100 if r['total_rtp'] > 0 else 0
        print(f"  base_rtp={r['base_rtp']:.3f}pp  feature_rtp={r['feature_rtp']:.3f}pp  "
              f"(split {split_b:.0f}:{split_f:.0f})")
        print(f"  R1_blank={r['r1_blank']:.3f}%  R2_blank={r['r2_blank']:.3f}%  R3_blank={r['r3_blank']:.3f}%")
        print(f"  trigger={r['trigger']:.3f}%  wild_cadence=1/{r['wild_cadence']:.0f}")
        s = r["session_bucket"]
        g510 = s.get("ge5_lt10", 0)
        g1020 = s.get("ge10_lt20", 0)
        sum120 = g15 + g510 + g1020
        print(f"  Buckets: g15={g15:.3f}  g510={g510:.3f}  g1020={g1020:.3f}  "
              f"sum120={sum120:.3f}")
        print(f"           g2050={s.get('ge20_lt50',0):.3f}  g50100={s.get('ge50_lt100',0):.3f}  "
              f"g100200={s.get('ge100_lt200',0):.3f}  g200500={s.get('ge200_lt500',0):.3f}")
        print(f"  v7 g15 low (target ≤13): {'YES' if g15_low else 'NO'} (g15={g15:.3f})")
        print(f"  v7 bar1_share ≤30%: {'YES' if bar1_ok else 'NO'} ({bar1_share:.2f}%)")
        print(f"  Family shares-of-base:")
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "high7", "wild_pure"):
            pp_val = (r['high7_combined_pp'] if fam == 'high7'
                      else r['family_pp'].get(fam, 0))
            print(f"    {fam:12s} {fs.get(fam,0):6.2f}%   ({pp_val:.3f}pp)")
        if family_violations:
            print(f"  Family violations: {family_violations}")
        if not cadence_ok:
            print(f"  Wild cadence OUT OF BAND [1/100k, 1/50k]: 1/{r['wild_cadence']:.0f}")
        if not rtp_safe:
            print(f"  RTP safety: total_rtp={r['total_rtp']:.3f} < 94.3pp")
        if n_fail > 0:
            print(f"  Hardline fails: {n_fail}/14")
            for nm, val, st, (lo, hi) in checks:
                if st == "FAIL":
                    print(f"    FAIL {nm:18s} = {val:8.3f}  target [{lo}, {hi}]")
        if strips is not None:
            tbl = pwdf_table(r["margs"], strips)
            print(f"  PWDF post-mech-B (max per reel):")
            for sym, row in tbl.items():
                print(f"    {sym:13s} R1={row[0]:6.2f} R2={row[1]:6.2f} R3={row[2]:6.2f} max={max(row):6.2f}")

    overall_pass = (n_fail == 0 and bar1_ok and not family_violations
                    and cadence_ok and rtp_safe)
    return overall_pass, {
        "checks": checks,
        "n_fail": n_fail,
        "bar1_share": bar1_share,
        "bar1_ok": bar1_ok,
        "family_violations": family_violations,
        "cadence_ok": cadence_ok,
        "rtp_safe": rtp_safe,
        "g15_low": g15_low,
        "r": r,
    }


# ============================================================
# Candidates — v7 direction
# ============================================================
# Density target: R1 non-blank ~60-65%, R2 ~50-55%, R3 ~42-48%.
# v13b ZZZ baseline (for ref): R1=60.9, R2=51.4, R3=43.1.
#
# Under v7 lower-bar1, the lost density must be made up by higher
# bar2/bar3/high7/cherry — or accept higher R1 blank (closer to 40 cap).
CANDIDATES = []


def cand_A():
    """A: bar1 18/16/14, bar2 12/11/10, bar3 5/5/4, cherry 4.5/3.5/3, h7 18/14/9, dd 2.6 unif.
    R1 nb = 4.5+18+12+5+18+2.6+0.4 = 60.5% → blank 39.5%."""
    R1 = {"cherry": 0.045, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.180, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.14, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("A", cand_A))


def cand_B():
    """B: bar1 20/17/15, bar2 11/10/9, bar3 4.5/4/3, cherry 4/3.5/3, h7 16/13/9, dd 2.6.
    R1 nb = 4+20+11+4.5+16+2.6+0.4 = 58.5% → blank 41.5% (just over cap)."""
    R1 = {"cherry": 0.045, "1bar": 0.20, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.09, "3bar": 0.03,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("B", cand_B))


def cand_C():
    """C: bar1 17/15/13, bar2 13/12/10, bar3 5/5/4, cherry 4.5/3.5/3, h7 17/14/10, dd 2.6.
    R1 nb = 4.5+17+13+5+17+2.6+0.4 = 59.5% → blank 40.5% slight cap-bust."""
    R1 = {"cherry": 0.050, "1bar": 0.17, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.15, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.13, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("C", cand_C))


def cand_D():
    """D: lower cherry — bar1 18/16/14, bar2 12/11/10, bar3 5/5/4, cherry 3/2.5/2, h7 19/15/10, dd 2.6.
    R1 nb = 3+18+12+5+19+2.6+0.4 = 60% → blank 40."""
    R1 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.190, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.16, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.14, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("D", cand_D))


def cand_E():
    """E: very low cherry — cherry 2/1.5/1, bar1 18/16/14, bar2 12/11/10, bar3 5/5/4, h7 21/17/11, dd 2.6.
    R1 nb = 2+18+12+5+21+2.6+0.4 = 61% → blank 39."""
    R1 = {"cherry": 0.020, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.210, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.16, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.010, "1bar": 0.14, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("E", cand_E))


def cand_F():
    """F: balance bar2 high — cherry 4/3/2.5, bar1 16/14/12, bar2 14/13/11, bar3 5/4.5/4, h7 17/14/10, dd 2.6.
    R1 nb = 4+16+14+5+17+2.6+0.4 = 59% → blank 41 (over cap, drop high7)."""
    R1 = {"cherry": 0.040, "1bar": 0.16, "2bar": 0.14, "3bar": 0.05,
          "high7": 0.180, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.14, "2bar": 0.13, "3bar": 0.045,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.12, "2bar": 0.11, "3bar": 0.040,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("F", cand_F))


def cand_G():
    """G: high7 heavy — cherry 3.5/3/2.5, bar1 17/15/13, bar2 11/10/9, bar3 4.5/4/3, h7 20/16/11, dd 2.6.
    R1 nb = 3.5+17+11+4.5+20+2.6+0.4 = 59% → blank 41."""
    R1 = {"cherry": 0.040, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.200, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.13, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("G", cand_G))


def cand_H():
    """H: bar1 22/19/16 (closer to v13b's 25), but lower others to compensate.
    cherry 4/3/2.5, bar2 9/8/7, bar3 4/4/3, h7 14/12/8, dd 2.5.
    R1 nb = 4+22+9+4+14+2.5+0.4 = 55.9% → blank 44 OVER. Lift h7 → 18 → 59.9% blank 40."""
    R1 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.09, "3bar": 0.04,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.08, "3bar": 0.04,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.16, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.090, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("H", cand_H))


def cand_I():
    """I: bar1 19/17/14, bar2 12/11/10, bar3 4.5/4/3, cherry 3.5/2.5/2, h7 17/14/10, dd 2.7.
    R1 nb = 3.5+19+12+4.5+17+2.7+0.4 = 59.1% → blank 40.9. Trim h7."""
    R1 = {"cherry": 0.035, "1bar": 0.19, "2bar": 0.12, "3bar": 0.045,
          "high7": 0.165, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.11, "3bar": 0.040,
          "high7": 0.135, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.14, "2bar": 0.10, "3bar": 0.030,
          "high7": 0.100, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("I", cand_I))


def cand_J():
    """J: cherry visible 4.5/4/3, bar1 16/14/12, bar2 11/10/9, bar3 4.5/4/3, h7 19/15/10, dd 2.7.
    R1 nb = 4.5+16+11+4.5+19+2.7+0.4 = 58.1% → blank 41.9 over.
    Lift h7 → 21. R1 nb = 60.1% blank 39.9."""
    R1 = {"cherry": 0.045, "1bar": 0.16, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.210, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.170, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.12, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.110, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("J", cand_J))


def cand_K():
    """K: low cherry + balanced — cherry 2.5/2/1.5, bar1 18/16/14, bar2 12/11/10, bar3 5/4.5/4,
    h7 20/16/11, dd 2.6.  R1 nb = 2.5+18+12+5+20+2.6+0.4 = 60.5% blank 39.5."""
    R1 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.200, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.16, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("K", cand_K))


def cand_L():
    """L: asymmetric dd — dd R1=2.4 R2=2.9 R3=2.5 → cube 1.74e-5 → 1/57k.
    cherry 4/3/2.5, bar1 18/16/14, bar2 12/11/10, bar3 5/4.5/4, h7 18/14/9.
    R1 nb = 4+18+12+5+18+2.4+0.4 = 59.8% blank 40.2 borderline."""
    R1 = {"cherry": 0.045, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.180, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.145, "doublediamond": 0.029, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.095, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("L", cand_L))


def cand_M():
    """M: bar1 21/18/15, bar2 11/10/9, bar3 4.5/4/3.5, cherry 4/3.5/3, h7 16/13/9, dd 2.7.
    R1 nb = 4+21+11+4.5+16+2.7+0.4 = 59.6% blank 40.4."""
    R1 = {"cherry": 0.040, "1bar": 0.21, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.165, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.130, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.095, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("M", cand_M))


def cand_N():
    """N: cherry mid 3.5/3/2.5, bar1 18/16/14, bar2 12/11/10, bar3 4.5/4/3, h7 18/14.5/10, dd 2.7.
    R1 nb = 3.5+18+12+4.5+18+2.7+0.4 = 59.1% blank 40.9 borderline.
    Trim cherry 4 → R1 nb 59.6."""
    R1 = {"cherry": 0.040, "1bar": 0.18, "2bar": 0.12, "3bar": 0.045,
          "high7": 0.180, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.11, "3bar": 0.040,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.030,
          "high7": 0.100, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("N", cand_N))


def cand_O():
    """O: bar1 lower 16/14/12, bar2 13/12/10, bar3 5/4.5/4, cherry 4/3/2.5, h7 18/14/9, dd 2.7.
    R1 nb = 4+16+13+5+18+2.7+0.4 = 59.1% blank 40.9."""
    R1 = {"cherry": 0.040, "1bar": 0.16, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.185, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.14, "2bar": 0.12, "3bar": 0.045,
          "high7": 0.150, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.12, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.105, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("O", cand_O))


def cand_P():
    """P: very wide bar — bar1 20/17/14, bar2 13/11/10, bar3 6/5/4, cherry 4/3/2.5, h7 14/11/8, dd 2.6.
    R1 nb = 4+20+13+6+14+2.6+0.4 = 60% blank 40."""
    R1 = {"cherry": 0.040, "1bar": 0.20, "2bar": 0.13, "3bar": 0.060,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.11, "3bar": 0.050,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("P", cand_P))


def cand_Q():
    """Q: balanced visible — cherry 4/3.5/3, bar1 18/16/14, bar2 12/11/10, bar3 5/4.5/4, h7 17/14/10, dd 2.7.
    R1 nb = 4+18+12+5+17+2.7+0.4 = 59.1% blank 40.9 borderline. Lift cherry."""
    R1 = {"cherry": 0.045, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.170, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.100, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("Q", cand_Q))


def cand_R():
    """R: target g15 ≈ 11pp — cherry 2.5/2/1.5, bar1 17/15/13, bar2 11/10/9, bar3 4.5/4/3, h7 19/15/10, dd 2.7.
    R1 nb = 2.5+17+11+4.5+19+2.7+0.4 = 57.1% blank 42.9 — over. Lift h7 → 21."""
    R1 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.210, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.15, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.170, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.13, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.110, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("R", cand_R))


def cand_S():
    """S: split cherry/bar — cherry 3/2.5/2, bar1 19/17/15, bar2 10/9/8, bar3 4/3.5/3, h7 18/14/10, dd 2.6.
    R1 nb = 3+19+10+4+18+2.6+0.4 = 57% blank 43 — over. Lift h7 → 20.5."""
    R1 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.205, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.165, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.15, "2bar": 0.08, "3bar": 0.030,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("S", cand_S))


def cand_T():
    """T: cherry 3.5/2.5/2, bar1 18/16/14, bar2 11/10/9, bar3 5/4.5/4, h7 18/14.5/10, dd 2.6.
    R1 nb = 3.5+18+11+5+18+2.6+0.4 = 58.5% blank 41.5 over. Lift cherry → 4."""
    R1 = {"cherry": 0.040, "1bar": 0.18, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.180, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.10, "3bar": 0.045,
          "high7": 0.145, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.09, "3bar": 0.040,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("T", cand_T))


def cand_U():
    """U: bar1 dominant but under 25 → cherry 4/3/2.5, bar1 22/19/16, bar2 9/8/7, bar3 4/3.5/3, h7 14/11.5/8, dd 2.6.
    R1 nb = 4+22+9+4+14+2.6+0.4 = 56% blank 44 over. Lift cherry 5 + h7 16 → R1 nb 60%."""
    R1 = {"cherry": 0.050, "1bar": 0.22, "2bar": 0.09, "3bar": 0.04,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.08, "3bar": 0.035,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("U", cand_U))


def cand_V():
    """V: dd 2.5 → 1.56e-5 → 1/64k. cherry 4/3/2.5, bar1 19/17/15, bar2 11/10/9, bar3 5/4.5/3.5, h7 17/14/10.
    R1 nb = 4+19+11+5+17+2.5+0.4 = 58.9% blank 41.1 borderline. Lift h7 → 18.5."""
    R1 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.185, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.10, "3bar": 0.045,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.15, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.105, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("V", cand_V))


def cand_W():
    """W: aim absolutely minimal g15 — cherry 1.5/1/0.8, bar1 17/15/13, bar2 11/10/9, bar3 4.5/4/3, h7 22/18/12, dd 2.7.
    R1 nb = 1.5+17+11+4.5+22+2.7+0.4 = 59.1% blank 40.9."""
    R1 = {"cherry": 0.015, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.220, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.010, "1bar": 0.15, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.180, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.008, "1bar": 0.13, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.120, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("W", cand_W))


def cand_X():
    """X: refined — cherry 3.5/3/2.5, bar1 19/17/15, bar2 11.5/10.5/9.5, bar3 4.5/4/3.5, h7 17/14/10, dd 2.6.
    R1 nb = 3.5+19+11.5+4.5+17+2.6+0.4 = 58.5% blank 41.5 — bump h7 → 18.5 → 60%."""
    R1 = {"cherry": 0.035, "1bar": 0.19, "2bar": 0.115, "3bar": 0.045,
          "high7": 0.185, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.105, "3bar": 0.040,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.15, "2bar": 0.095, "3bar": 0.035,
          "high7": 0.105, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("X", cand_X))


def cand_Y():
    """Y: high cherry visible / low bar — cherry 5/4/3, bar1 16/14/12, bar2 12/11/10, bar3 5/4.5/4, h7 16/13/9, dd 2.6.
    R1 nb = 5+16+12+5+16+2.6+0.4 = 57% blank 43 over. Lift h7 → 19.
    R1 nb = 60% blank 40."""
    R1 = {"cherry": 0.050, "1bar": 0.16, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.190, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.14, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.12, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.105, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("Y", cand_Y))


def cand_Z():
    """Z: final attempt — combine best knobs.
    cherry 3.5/3/2.5, bar1 18/16/14, bar2 12/11/10, bar3 5/4.5/3.5, h7 18/14.5/10, dd 2.6.
    R1 nb = 3.5+18+12+5+18+2.6+0.4 = 59.5% blank 40.5 — bump cherry → 4."""
    R1 = {"cherry": 0.040, "1bar": 0.18, "2bar": 0.12, "3bar": 0.050,
          "high7": 0.180, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.145, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.035,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("Z", cand_Z))


# Second wave — explicit max-density attack: every family hits share-cap-implied max
def cand_AA():
    """AA: bar1 18/15/13, bar2 14/13/11, bar3 6/5.5/4.5, cherry 5/4/3, h7 13/11/7.5, dd 2.7.
    R1 nb = 5+18+14+6+13+2.7+0.4 = 59.1% blank 40.9 — bump cherry → 5.5."""
    R1 = {"cherry": 0.055, "1bar": 0.18, "2bar": 0.14, "3bar": 0.06,
          "high7": 0.130, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.15, "2bar": 0.13, "3bar": 0.055,
          "high7": 0.110, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.13, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.075, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AA", cand_AA))


def cand_BB():
    """BB: bar1 19/16/14, bar2 13/11/10, bar3 6/5/4, cherry 4.5/3.5/2.5, h7 12/10/7, dd 2.6.
    R1 nb = 4.5+19+13+6+12+2.6+0.4 = 57.5% blank 42.5 over. Lift h7 → 14.5
    R1 nb = 60% blank 40."""
    R1 = {"cherry": 0.045, "1bar": 0.19, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.145, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BB", cand_BB))


def cand_CC():
    """CC: bar1 20/17/15, bar2 12/11/10, bar3 5/4.5/4, cherry 4.5/3.5/2.5, h7 13/11/8, dd 2.6.
    R1 nb = 4.5+20+12+5+13+2.6+0.4 = 57.5% blank 42.5. Lift h7 → 15.5."""
    R1 = {"cherry": 0.045, "1bar": 0.20, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.15, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CC", cand_CC))


def cand_DD():
    """DD: balance with mid h7 — bar1 18/16/14, bar2 13/12/10, bar3 5.5/5/4, cherry 4.5/3.5/2.5,
    h7 12/10/7, dd 2.6. R1 nb = 4.5+18+13+5.5+12+2.6+0.4 = 56% blank 44 over. Lift h7 → 16."""
    R1 = {"cherry": 0.045, "1bar": 0.18, "2bar": 0.13, "3bar": 0.055,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.12, "3bar": 0.050,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DD", cand_DD))


def cand_EE():
    """EE: cherry mid + bar1 mid — cherry 4/3/2.5, bar1 19/17/14, bar2 13/11/10, bar3 5/4.5/4, h7 14/12/8, dd 2.7.
    R1 nb = 4+19+13+5+14+2.7+0.4 = 58.1% blank 41.9. Lift h7 → 16."""
    R1 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.160, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.135, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.090, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EE", cand_EE))


def cand_FF():
    """FF: cherry low — cherry 3/2.5/2, bar1 19/17/15, bar2 13/11/10, bar3 5/4.5/4, h7 14/12/8, dd 2.7.
    R1 nb = 3+19+13+5+14+2.7+0.4 = 57.1% blank 42.9 over. Lift h7 → 17."""
    R1 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.170, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.15, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.095, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FF", cand_FF))


def cand_GG():
    """GG: bar1 hits the 22% — bar1 22/19/16, bar2 11/10/9, bar3 5/4.5/4, cherry 4/3.5/3, h7 12/10/7, dd 2.6.
    R1 nb = 4+22+11+5+12+2.6+0.4 = 57% blank 43 over. Lift h7 → 15."""
    R1 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.11, "3bar": 0.05,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.19, "2bar": 0.10, "3bar": 0.045,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.09, "3bar": 0.040,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GG", cand_GG))


def cand_HH():
    """HH: keep h7 mid 13/11/8 — bar1 22/19/16, bar2 12/11/10, bar3 5/4.5/4, cherry 4/3/2.5, h7 13/11/8, dd 2.6.
    R1 nb = 4+22+12+5+13+2.6+0.4 = 59% blank 41 over. Lift h7 → 14."""
    R1 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.16, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HH", cand_HH))


def cand_II():
    """II: aim g15 ~ 12 — moderately low cherry, low bar densities; rely on h7 to fill R1.
    cherry 3/2.5/2, bar1 17/15/13, bar2 10/9/8, bar3 4/3.5/3, h7 17/14/10, dd 2.7.
    R1 nb = 3+17+10+4+17+2.7+0.4 = 54.1% blank 45.9 over. Lift h7 → 20.
    R1 nb = 57.1% blank 42.9 over. h7 → 23. R1 nb 60.1 blank 39.9 ✓ but h7 share will blow up."""
    R1 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.225, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.15, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.180, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.13, "2bar": 0.08, "3bar": 0.030,
          "high7": 0.120, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("II", cand_II))


def cand_JJ():
    """JJ: most-balanced w/ bar1 mod-low — bar1 19/16/13, bar2 13/12/10, bar3 6/5/4.5, cherry 4.5/3.5/3, h7 14/12/8, dd 2.6.
    R1 nb = 4.5+19+13+6+14+2.6+0.4 = 59.5% blank 40.5 ✓
    Try this exact config."""
    R1 = {"cherry": 0.045, "1bar": 0.19, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.13, "2bar": 0.10, "3bar": 0.045,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJ", cand_JJ))


def cand_KK():
    """KK: similar JJ but bar1 a bit higher 20/17/14.5 — try push bar1 share toward 30 cap.
    R1 nb = 4.5+20+12+5+13+2.6+0.4 = 57.5 + 0 = 57.5% blank 42.5. Lift h7 to 16.
    R1 nb 60.5 blank 39.5 ✓."""
    R1 = {"cherry": 0.045, "1bar": 0.20, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.145, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KK", cand_KK))


def cand_LL():
    """LL: aim total_rtp = 95 exactly — lower h7 to 12/10/7 and accept R1 blank 41+.
    Hardline H3 fails BUT see how close other metrics are.
    cherry 4/3/2.5, bar1 19/17/14, bar2 12/11/10, bar3 5/4.5/4, h7 12/10/7, dd 2.7.
    R1 nb = 4+19+12+5+12+2.7+0.4 = 55.1% → blank 44.9. Just need to see if it works in other dimensions."""
    R1 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.100, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.070, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LL", cand_LL))


# Wave 3 — lower total bar density to push g15 down (target g15 ≤ 13).
# Math: bar_mixed_pure ≈ 2 * (B1*B2*B3 - b1_prod - b2_prod - b3_prod)
# where Bi = sum of bars on reel i. Lower B reduces bar_mixed_pure (g15).
# cherry-1 also drives g15. Reduce cherry per reel.
def cand_MM():
    """MM: aim g15 ≤ 13. bar1 18/15/12, bar2 10/8/7, bar3 4/3/2.5 (total bars 32/26/21.5),
    cherry 4/3/2.5, h7 14/13/9, dd 2.6.
    R1 nb = 4+18+10+4+14+2.6+0.4 = 53% blank 47 over. Lift h7 → 21.
    R1 nb = 60% blank 40. h7=21 will blow share."""
    R1 = {"cherry": 0.040, "1bar": 0.18, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.210, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.08, "3bar": 0.030,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.12, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("MM", cand_MM))


def cand_NN():
    """NN: similar to HH (close to pass) but lower bar2/bar3 to drop bar_mixed.
    bar1 22/19/16, bar2 9/8/7, bar3 3/2.5/2, cherry 3.5/2.5/2, h7 16/14/10, dd 2.6.
    R1 nb = 3.5+22+9+3+16+2.6+0.4 = 56.5% blank 43.5 over. Lift h7 → 19.5.
    R1 nb = 60% blank 40."""
    R1 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.195, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.19, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.16, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("NN", cand_NN))


def cand_OO():
    """OO: HH variant — lower cherry to bring g15 down. bar1 22/19/16, bar2 12/11/10, bar3 5/4.5/4,
    cherry 2.5/2/1.5, h7 14/11/8, dd 2.6.
    R1 nb = 2.5+22+12+5+14+2.6+0.4 = 58.5% blank 41.5. Lift h7 → 15.5."""
    R1 = {"cherry": 0.025, "1bar": 0.22, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.19, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.16, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("OO", cand_OO))


def cand_PP():
    """PP: split the difference — cherry 3/2.5/2, bar1 22/19/16, bar2 11/10/9, bar3 4.5/4/3.5,
    h7 14/12/8, dd 2.6.
    R1 nb = 3+22+11+4.5+14+2.6+0.4 = 57.5 blank 42.5. Lift h7 → 16.5."""
    R1 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.11, "3bar": 0.045,
          "high7": 0.165, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.19, "2bar": 0.10, "3bar": 0.040,
          "high7": 0.135, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.16, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PP", cand_PP))


def cand_QQ():
    """QQ: aim g15 ~12 — very low cherry + low bar. cherry 2/1.5/1, bar1 18/16/14, bar2 9/8/7, bar3 3.5/3/2.5,
    h7 17/14/10, dd 2.6.
    R1 nb = 2+18+9+3.5+17+2.6+0.4 = 52.5 blank 47.5 — over. Lift h7 → 22.
    R1 nb = 57.5 blank 42.5 still over. h7 → 24. R1 nb 59.5 blank 40.5.
    h7 share will blow up."""
    R1 = {"cherry": 0.020, "1bar": 0.18, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.240, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.16, "2bar": 0.08, "3bar": 0.030,
          "high7": 0.190, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.010, "1bar": 0.14, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.130, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("QQ", cand_QQ))


def cand_RR():
    """RR: Compromise on bar1 share — accept ~35% but balance other families well.
    bar1 24/21/17 (slight above ZZZ's bar1 25/22/18), bar2 8/7/6, bar3 3.5/3/2.5, cherry 4/3/2.5,
    h7 12/10/7, dd 2.6. — pure 1bar driving g510 instead of g15.
    R1 nb = 4+24+8+3.5+12+2.6+0.4 = 54.5 blank 45.5 over. Lift h7 → 17.5."""
    R1 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.08, "3bar": 0.035,
          "high7": 0.175, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.21, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("RR", cand_RR))


def cand_SS():
    """SS: replicate ZZZ structure but trim cherry — see baseline of structural floor.
    cherry 3.5/2.5/2, bar1 30/26/22 (down from ZZZ's 34/30/25 by 4 each), bar2 6/5.5/5, bar3 1.8/1.5/1.3,
    h7 14/10.5/7, dd 2.5, jp 0.4.
    R1 nb = 3.5+30+6+1.8+14+2.5+0.4 = 58.2% blank 41.8 over. Lift cherry → 4."""
    R1 = {"cherry": 0.040, "1bar": 0.30, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.26, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.105, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.22, "2bar": 0.05, "3bar": 0.013,
          "high7": 0.070, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("SS", cand_SS))


def cand_TT():
    """TT: between ZZZ and HH. bar1 25/22/18 (= ZZZ), bar2 8/7/6, bar3 2.5/2/1.5, cherry 3.5/2.5/2,
    h7 13/10/7, dd 2.6, jp 0.4.
    R1 nb = 3.5+25+8+2.5+13+2.6+0.4 = 55% blank 45 over. Lift cherry → 4.5 + h7 → 16.
    R1 nb = 59.5 blank 40.5 borderline."""
    R1 = {"cherry": 0.045, "1bar": 0.25, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("TT", cand_TT))


def cand_UU():
    """UU: bar1 28/24/20 (slightly less than ZZZ's 34/30/25), bar2 7/6/5, bar3 2/1.8/1.5,
    cherry 4/3/2.5, h7 12/10/7, dd 2.6, jp 0.4.
    R1 nb = 4+28+7+2+12+2.6+0.4 = 56% blank 44 over. Lift h7 → 16.
    R1 nb = 60% blank 40 ✓."""
    R1 = {"cherry": 0.040, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("UU", cand_UU))


def cand_VV():
    """VV: bar1 26/22/18, bar2 9/8/7, bar3 3/2.5/2, cherry 4/3/2.5, h7 12/10/7, dd 2.7, jp 0.4.
    R1 nb = 4+26+9+3+12+2.7+0.4 = 57.1 blank 42.9 over. Lift h7 → 14.5.
    R1 nb = 59.6 blank 40.4 borderline."""
    R1 = {"cherry": 0.040, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("VV", cand_VV))


def cand_WW():
    """WW: target bar1 share = 30%. bar1 22/19/16 (will push share ~32%), bar2 10/9/8,
    bar3 4/3.5/3, cherry 3.5/3/2.5, h7 14/12/8, dd 2.7, jp 0.4.
    R1 nb = 3.5+22+10+4+14+2.7+0.4 = 56.6 blank 43.4 over. Lift h7 → 17.5.
    R1 nb = 60.1 blank 39.9 ✓."""
    R1 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.175, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.16, "2bar": 0.08, "3bar": 0.030,
          "high7": 0.100, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("WW", cand_WW))


def cand_XX():
    """XX: slightly lower bar1, tighter family balance — bar1 24/20/17, bar2 9/8/7, bar3 3.5/3/2.5,
    cherry 3.5/3/2.5, h7 14/11/8, dd 2.6, jp 0.4.
    R1 nb = 3.5+24+9+3.5+14+2.6+0.4 = 57 blank 43 over. Lift h7 → 17.
    R1 nb = 60 blank 40 ✓."""
    R1 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.08, "3bar": 0.030,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("XX", cand_XX))


def cand_YY():
    """YY: aim g15 close to 13 — bar1 23/20/17, bar2 9/8/7, bar3 3/2.5/2, cherry 3/2.5/2, h7 13/11/8, dd 2.6.
    R1 nb = 3+23+9+3+13+2.6+0.4 = 54 blank 46. Lift h7 → 19.
    R1 nb = 60 blank 40 ✓."""
    R1 = {"cherry": 0.030, "1bar": 0.23, "2bar": 0.09, "3bar": 0.03,
          "high7": 0.190, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.110, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("YY", cand_YY))


# Wave 4 — UU was the closest. Iterate around UU to fix hit + g50100.
# UU: cherry 4/3/2.5, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 16/13/9, dd 2.6.
# Fixes needed:
#   - hit_session 14.61% → ≥ 15%. Lift cherry (cheap hit boost) or bar marginal.
#   - g50100 27.87 → ≤ 27. Trim h7 slightly (pay_id 2 30×/60× lands g2050+g50100).
def cand_ZZ():
    """ZZ: UU + cherry up + h7 down. cherry 4.5/3.5/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5,
    h7 15/12.5/8.5, dd 2.6, jp 0.4.
    R1 nb = 4.5+28+7+2+15+2.6+0.4 = 59.5% blank 40.5 borderline."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("ZZ", cand_ZZ))


def cand_AAA():
    """AAA: UU + cherry up. cherry 5/4/3.5, bar1 26/22/18, bar2 7/6/5, bar3 2/1.8/1.5, h7 15/12.5/8.5,
    dd 2.6, jp 0.4.
    R1 nb = 5+26+7+2+15+2.6+0.4 = 58 blank 42. Lift h7 → 17.
    R1 nb = 60 blank 40 ✓."""
    R1 = {"cherry": 0.050, "1bar": 0.26, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.135, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.095, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AAA", cand_AAA))


def cand_BBB():
    """BBB: UU + cherry 5 + h7 14/11.5/8 (drop further). cherry 5/4/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5,
    h7 14/11.5/8, dd 2.6, jp 0.4.
    R1 nb = 5+28+7+2+14+2.6+0.4 = 59 blank 41 over. Lift cherry → 5.5."""
    R1 = {"cherry": 0.055, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BBB", cand_BBB))


def cand_CCC():
    """CCC: UU + cherry 5 + bar2 8 (lift bar2 for visibility, slight g510/g1020 lift).
    cherry 5/4/3, bar1 27/23/19, bar2 8/7/6, bar3 2/1.8/1.5, h7 14/11.5/8, dd 2.6, jp 0.4.
    R1 nb = 5+27+8+2+14+2.6+0.4 = 59 blank 41. Lift h7 → 15.
    R1 nb = 60 blank 40."""
    R1 = {"cherry": 0.050, "1bar": 0.27, "2bar": 0.08, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.23, "2bar": 0.07, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CCC", cand_CCC))


def cand_DDD():
    """DDD: UU + bar3 lifted to 3 for share. cherry 4.5/3.5/3, bar1 27/23/19, bar2 7/6/5, bar3 3/2.5/2,
    h7 14/11.5/8, dd 2.6, jp 0.4.
    R1 nb = 4.5+27+7+3+14+2.6+0.4 = 58.5 blank 41.5. Lift h7 → 15.5."""
    R1 = {"cherry": 0.045, "1bar": 0.27, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.23, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DDD", cand_DDD))


def cand_EEE():
    """EEE: UU + cherry 5 + h7 12/10/7. cherry 5/4/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5,
    h7 12/10/7, dd 2.6, jp 0.4.
    R1 nb = 5+28+7+2+12+2.6+0.4 = 57 blank 43 over. Lift h7 → 17.
    R1 nb = 62 blank 38 ✓."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.135, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.095, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EEE", cand_EEE))


def cand_FFF():
    """FFF: aim absolute best — based on UU but cherry 5/4/3, h7 12/10/7, dd 2.7.
    R1 nb = 5+28+7+2+12+2.7+0.4 = 57.1 blank 42.9. Lift cherry → 6 + h7 → 14.
    Try config."""
    R1 = {"cherry": 0.060, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.110, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.075, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FFF", cand_FFF))


def cand_GGG():
    """GGG: stretching bar1 R1 to 30 with all other tier hits 0 (proxy for v7 boundary).
    cherry 4.5/3.5/3, bar1 30/26/22, bar2 5/4/3.5, bar3 1.5/1.2/1, h7 14/11.5/8, dd 2.6, jp 0.4.
    R1 nb = 4.5+30+5+1.5+14+2.6+0.4 = 58 blank 42. Lift cherry → 6.
    R1 nb = 59.5 blank 40.5 borderline."""
    R1 = {"cherry": 0.055, "1bar": 0.30, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.04, "3bar": 0.012,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.035, "3bar": 0.010,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GGG", cand_GGG))


def cand_HHH():
    """HHH: more conservative. bar1 28/24/20, bar2 7/6/5, bar3 2.5/2/1.5, cherry 4.5/3.5/3,
    h7 13.5/11/8, dd 2.6, jp 0.4.
    R1 nb = 4.5+28+7+2.5+13.5+2.6+0.4 = 58.5 blank 41.5. Lift h7 → 15."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HHH", cand_HHH))


def cand_III():
    """III: UU + slight cherry bump + h7 13.5/11/8 (mid h7).
    R1 nb = 4.5+28+7+2+13.5+2.6+0.4 = 58 blank 42. Lift cherry → 5.5."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("III", cand_III))


def cand_JJJ():
    """JJJ: even cherrier — cherry 6/4.5/3.5, bar1 25/22/18, bar2 7/6/5, bar3 2/1.8/1.5, h7 13/11/8, dd 2.6.
    R1 nb = 6+25+7+2+13+2.6+0.4 = 56 blank 44. Lift h7 → 17.
    R1 nb = 60 blank 40."""
    R1 = {"cherry": 0.060, "1bar": 0.25, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.170, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.22, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJJ", cand_JJJ))


def cand_KKK():
    """KKK: cherry 5/4/3 + h7 13/11/7.5 (target g50100 below 27). bar1 28/24/20, bar2 7/6/5,
    bar3 2.5/2/1.5, dd 2.6, jp 0.4.
    R1 nb = 5+28+7+2.5+13+2.6+0.4 = 58.5 blank 41.5. Lift h7 → 15.
    R1 nb = 60.5 blank 39.5."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KKK", cand_KKK))


# Wave 5 — tight iteration around UU/AAA, trying to hit both hit≥15 AND g50100≤27.
# AAA failed total_rtp 96.06 (over by 0.06) + g15 15.97 (over by 0.97)
# UU failed hit 14.61 (under 0.4) + g50100 27.87 (over 0.87)
# Tradeoff: cherry up → hit up but g15 up; h7 down → g50100 down + rtp down.
def cand_LLL():
    """LLL: between UU and AAA. cherry 4.5/3.5/3, bar1 27/23/19, bar2 7/6/5, bar3 2/1.8/1.5,
    h7 13.5/11/8, dd 2.6, jp 0.4.
    R1 nb = 4.5+27+7+2+13.5+2.6+0.4 = 57 blank 43. Lift h7 → 16.
    R1 nb = 59.5 blank 40.5 borderline."""
    R1 = {"cherry": 0.045, "1bar": 0.27, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.23, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LLL", cand_LLL))


def cand_MMM():
    """MMM: cherry 5/3.8/3, bar1 27/23/19, bar2 7.5/6.5/5.5, bar3 2.5/2/1.7, h7 14/11.5/8, dd 2.7.
    R1 nb = 5+27+7.5+2.5+14+2.7+0.4 = 59.1 blank 40.9 over (just). Trim cherry → 4.5.
    R1 nb 58.6 blank 41.4. Lift h7 → 14.5.
    R1 nb 59.1 still over. Try cherry → 4.8."""
    R1 = {"cherry": 0.048, "1bar": 0.27, "2bar": 0.075, "3bar": 0.025,
          "high7": 0.150, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.038, "1bar": 0.23, "2bar": 0.065, "3bar": 0.020,
          "high7": 0.125, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.055, "3bar": 0.017,
          "high7": 0.085, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("MMM", cand_MMM))


def cand_NNN():
    """NNN: AAA minus a bit. cherry 4.8/3.8/3, bar1 26/22/18, bar2 7/6/5, bar3 2/1.8/1.5, h7 16/13/9, dd 2.6.
    R1 nb = 4.8+26+7+2+16+2.6+0.4 = 58.8 blank 41.2 over. Lift cherry → 5.2."""
    R1 = {"cherry": 0.052, "1bar": 0.26, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.032, "1bar": 0.18, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("NNN", cand_NNN))


def cand_OOO():
    """OOO: trim AAA cherry — cherry 4.5/3.5/2.5, bar1 26/22/18, bar2 7/6/5, bar3 2/1.8/1.5, h7 16/13/9, dd 2.6.
    R1 nb = 4.5+26+7+2+16+2.6+0.4 = 58.5 blank 41.5. Lift h7 → 17.5."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.175, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("OOO", cand_OOO))


def cand_PPP():
    """PPP: dd lower 2.4 (cadence 1/72k) + cherry 4.5 + h7 14/11.5/8. bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5.
    R1 nb = 4.5+28+7+2+14+2.4+0.4 = 58.3 blank 41.7. Lift h7 → 16."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP", cand_PPP))


def cand_QQQ():
    """QQQ: based on UU + cherry 4.5 + h7 14/11/8. UU had cherry 4/3/2.5, bar1 28/24/20, bar2 7/6/5,
    bar3 2/1.8/1.5, h7 16/13/9.
    Try: cherry 4.5/3.5/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 14/11/8, dd 2.7.
    R1 nb = 4.5+28+7+2+14+2.7+0.4 = 58.6 blank 41.4. Lift cherry → 5.
    R1 nb = 59.1 blank 40.9 borderline."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.038, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("QQQ", cand_QQQ))


def cand_RRR():
    """RRR: cherry 4.5/3.5/3, bar1 26/22/18, bar2 8/7/6 (lift bar2 share), bar3 2.5/2/1.5,
    h7 14/11.5/8, dd 2.6, jp 0.4.
    R1 nb = 4.5+26+8+2.5+14+2.6+0.4 = 58 blank 42. Lift h7 → 16."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.160, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("RRR", cand_RRR))


def cand_SSS():
    """SSS: lower h7 + lift cherry. cherry 5/4/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5,
    h7 12.5/10/7, dd 2.7, jp 0.4.
    R1 nb = 5+28+7+2+12.5+2.7+0.4 = 57.6 blank 42.4. Lift cherry → 5.8."""
    R1 = {"cherry": 0.058, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.125, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.100, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.070, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("SSS", cand_SSS))


def cand_TTT():
    """TTT: cherry 5.5/4.5/3.5, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 13/10.5/7, dd 2.6.
    R1 nb = 5.5+28+7+2+13+2.6+0.4 = 58.5 blank 41.5. Lift h7 → 15."""
    R1 = {"cherry": 0.055, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.078, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("TTT", cand_TTT))


def cand_UUU():
    """UUU: same as UU but trim h7 R1 from 16 to 14, lift cherry R1 from 4 to 5.
    cherry 5/4/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 14/11.5/8, dd 2.6.
    R1 nb = 5+28+7+2+14+2.6+0.4 = 59 blank 41 borderline."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("UUU", cand_UUU))


def cand_VVV():
    """VVV: same as UUU but bar2 R1 8 (better bar2 share). cherry 5/4/3, bar1 26/22/18.5,
    bar2 8/7/6, bar3 2.5/2/1.5, h7 14/11.5/8, dd 2.6.
    R1 nb = 5+26+8+2.5+14+2.6+0.4 = 58.5 blank 41.5. Lift h7 → 15.5."""
    R1 = {"cherry": 0.050, "1bar": 0.26, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.185, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.088, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("VVV", cand_VVV))


def cand_WWW():
    """WWW: heavy cherry. cherry 5.5/4.5/3, bar1 27/23/19, bar2 7/6/5, bar3 2/1.8/1.5, h7 13/10.5/7, dd 2.6.
    R1 nb = 5.5+27+7+2+13+2.6+0.4 = 57.5 blank 42.5. Lift h7 → 15.5."""
    R1 = {"cherry": 0.055, "1bar": 0.27, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.23, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("WWW", cand_WWW))


# Wave 6 — iterate around PPP (95.23pp, only fails g50100 by 0.26pp).
# PPP was: cherry 4.5/3.5/2.5, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 16/13/9, dd 2.4.
# Drop h7 → drop g50100 + drop high7 share simultaneously. Compensate with bar2 lift.
def cand_XXX():
    """XXX: PPP with h7 trimmed to 14/11.5/8 and bar2 lifted to 8/7/6.
    R1 nb = 4.5+28+8+2+14+2.4+0.4 = 59.3 blank 40.7 over. Lift cherry → 5."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.08, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.07, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("XXX", cand_XXX))


def cand_YYY():
    """YYY: PPP with h7 15/12.5/8.5 (small h7 trim from 16).
    R1 nb = 4.5+28+7+2+15+2.4+0.4 = 59.3 blank 40.7. Lift cherry → 5."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("YYY", cand_YYY))


def cand_ZZZ():
    """ZZZ: PPP with h7 15/12/8 (slightly more trim). cherry 5/4/3 lifted to push hit.
    R1 nb = 5+28+7+2+15+2.4+0.4 = 59.8 blank 40.2 — right at cap. Try cherry 4.7."""
    R1 = {"cherry": 0.047, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.037, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.028, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("ZZZ", cand_ZZZ))


def cand_AAAA():
    """AAAA: PPP exact + h7 R2 cut from 13 to 12.5 (small step).
    R1 nb = 4.5+28+7+2+16+2.4+0.4 = 60.3 blank 39.7 ✓ (matches PPP)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.087, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AAAA", cand_AAAA))


def cand_BBBB():
    """BBBB: PPP + h7 trimmed to 15/12.5/9 + dd up to 2.5 (cadence). bar1 down to 27/23/19.
    R1 nb = 4.5+27+7+2+15+2.5+0.4 = 58.4 blank 41.6. Lift cherry → 5.6."""
    R1 = {"cherry": 0.056, "1bar": 0.27, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.044, "1bar": 0.23, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.032, "1bar": 0.19, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BBBB", cand_BBBB))


def cand_CCCC():
    """CCCC: PPP + h7 14.5/12/8.5 + cherry 4.8/3.8/2.8. R1 nb = 4.8+28+7+2+14.5+2.4+0.4 = 59.1 blank 40.9.
    Trim h7 R1 → 14, lift cherry → 5.4: R1 nb 59.2 blank 40.8 just over."""
    R1 = {"cherry": 0.054, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.082, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CCCC", cand_CCCC))


def cand_DDDD():
    """DDDD: PPP base + h7 15/12.5/8.5 + bar2 7.5/6.5/5.5 to nudge g510 up too.
    R1 nb = 4.5+28+7.5+2+15+2.4+0.4 = 59.8 blank 40.2."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.075, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.065, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DDDD", cand_DDDD))


def cand_EEEE():
    """EEEE: lift cherry on R2 + R3 (where it helps hit but doesn't blow g15 too much).
    cherry 4.5/4/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 15.5/12/8, dd 2.4, jp 0.4.
    R1 nb = 4.5+28+7+2+15.5+2.4+0.4 = 59.8 blank 40.2 borderline."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EEEE", cand_EEEE))


def cand_FFFF():
    """FFFF: PPP + reduce dd to 2.3 → cadence 1/82k. Compensate non-blank with h7 +0.1.
    cherry 4.5/3.5/2.5, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 16.1/13.1/9.1, dd 2.3."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.161, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.131, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.092, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FFFF", cand_FFFF))


def cand_GGGG():
    """GGGG: PPP exact (replicate baseline to confirm)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GGGG", cand_GGGG))


def cand_HHHH():
    """HHHH: PPP-like with extra h7 trim and bar2 lift. cherry 4.5, bar1 28/24/20, bar2 8/7/6,
    bar3 2/1.8/1.5, h7 14.5/12/8, dd 2.4."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.08, "3bar": 0.020,
          "high7": 0.145, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.07, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HHHH", cand_HHHH))


def cand_IIII():
    """IIII: PPP + much trimmed h7 (12.5/10/7) + heavy cherry (6/4.5/3.5).
    R1 nb = 6+28+7+2+12.5+2.4+0.4 = 58.3 blank 41.7. Lift cherry → 7.3
    nope. Try h7 → 14.5. R1 nb = 60.3 blank 39.7."""
    R1 = {"cherry": 0.060, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.145, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.078, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("IIII", cand_IIII))


# Wave 7 — VV-derived (bar1 26, bar2 9, bar3 3) had VV g50100=26.95 ✓ but R1 blank 40.4 over.
# Lift R1 density by 0.4pp via cherry (0.4 lift adds 0.4pp cherry-1 RTP to g15, manageable).
def cand_JJJJ():
    """JJJJ: VV + cherry R1 4→4.5. R1 nb = 4.5+26+9+3+14.5+2.7+0.4 = 60.1 blank 39.9 ✓."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJJJ", cand_JJJJ))


def cand_KKKK():
    """KKKK: VV + dd R1 lifted 2.7 → 3.0 (cadence 1/45k out band, but try)."""
    R1 = {"cherry": 0.040, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KKKK", cand_KKKK))


def cand_LLLL():
    """LLLL: VV + bar2 lift R1 9→9.5 (compensate density without cherry / RTP)."""
    R1 = {"cherry": 0.040, "1bar": 0.26, "2bar": 0.095, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LLLL", cand_LLLL))


def cand_MMMM():
    """MMMM: VV + jackpot R1 lift 0.4→0.5 (no RTP impact since 1000× blocked)."""
    R1 = {"cherry": 0.040, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.005}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("MMMM", cand_MMMM))


def cand_NNNN():
    """NNNN: VV + cherry R1 4→4.3 (small lift)."""
    R1 = {"cherry": 0.043, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("NNNN", cand_NNNN))


def cand_OOOO():
    """OOOO: JJJJ but check effect — same R1 cherry 4.5, bar1 26, bar2 9, bar3 3 (R1 nb = 60.1)."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("OOOO", cand_OOOO))


def cand_PPPP():
    """PPPP: JJJJ + R2 cherry 3 → 3.5 (lift hit overall). R2 nb = 3.5+22+8+2.5+12+2.7+0.4 = 51.1."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPPP", cand_PPPP))


def cand_QQQQ():
    """QQQQ: JJJJ + R1 h7 14.5→14 trim (lower g50100). compensate with cherry R1 → 5.
    R1 nb = 5+26+9+3+14+2.7+0.4 = 60.1 blank 39.9 ✓."""
    R1 = {"cherry": 0.050, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("QQQQ", cand_QQQQ))


def cand_RRRR():
    """RRRR: JJJJ + h7 R2/R3 trim (12→11.5, 8→7.5). cherry 4.5/3/2.5, bar1 26/22/18, bar2 9/8/7,
    bar3 3/2.5/2, h7 14.5/11.5/7.5, dd 2.7.
    R2 nb = 3+22+8+2.5+11.5+2.7+0.4 = 50.1 blank 49.9.
    R3 nb = 2.5+18+7+2+7.5+2.7+0.4+1.1 = 41.2 blank 58.8."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("RRRR", cand_RRRR))


def cand_SSSS():
    """SSSS: JJJJ-variant with bar2 lifted on all reels for share. bar2 11/10/9, bar1 25/21/17.
    R1 nb = 4.5+25+11+3+14.5+2.7+0.4 = 61.1 blank 38.9 ✓."""
    R1 = {"cherry": 0.045, "1bar": 0.25, "2bar": 0.11, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.21, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.09, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("SSSS", cand_SSSS))


def cand_TTTT():
    """TTTT: JJJJ + h7 R1 14.5→13.5 (g50100 drop). compensate with cherry R1 → 5.5.
    R1 nb = 5.5+26+9+3+13.5+2.7+0.4 = 60.1 blank 39.9 ✓."""
    R1 = {"cherry": 0.055, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.135, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("TTTT", cand_TTTT))


# Wave 8 — laser-focus on PPP. PPP failed only g50100 by 0.26pp.
# Cut h7 product (R1*R2*R3 high7 → all 3 line wins) — biggest leverage on g50100.
# Cut h7 R2 specifically (R2 is the median: changes hit prob most for pay_id 2/21).
def cand_UUUU():
    """UUUU: PPP + h7 R2 13→12. R2 nb drops 1pp → blank rises 1pp. Compensate cherry R2 +1 or bar2 R2 +1.
    R2 nb (PPP) = 3.5+24+6+1.8+13+2.4+0.4 = 51.1. -1 → 50.1, +cherry 4.5: 51.1. Same.
    Net: cherry R2 3.5 → 4.5, h7 R2 13 → 12."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("UUUU", cand_UUUU))


def cand_VVVV():
    """VVVV: PPP + h7 R3 9→8 (smallest leverage). compensate cherry R3 2.5→3.5."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("VVVV", cand_VVVV))


def cand_WWWW():
    """WWWW: PPP + ALL h7 trimmed (16→15, 13→12.2, 9→8.5). compensate cherry +0.7 R1, +0.5 R2.
    R1 nb = 5.2+28+7+2+15+2.4+0.4 = 60.0 blank 40.0 borderline."""
    R1 = {"cherry": 0.052, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.043, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.122, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.028, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("WWWW", cand_WWWW))


def cand_XXXX():
    """XXXX: PPP + h7 R1 16→15.5, h7 R2 13→12.5, h7 R3 9→8.5. compensate cherry.
    R1 nb = 5+28+7+2+15.5+2.4+0.4 = 60.3 blank 39.7."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("XXXX", cand_XXXX))


def cand_YYYY():
    """YYYY: PPP + cut h7 R2 only (13→11.5). compensate bar2 R2 6→7.5 (more bar2 share, marginal g510)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.075, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("YYYY", cand_YYYY))


def cand_ZZZZ():
    """ZZZZ: VV-derived (which had g50100=26.95 PASS) + cherry R1 +0.5 to fix R1 blank.
    cherry 4.5/3/2.5, bar1 26/22/18, bar2 9/8/7, bar3 3/2.5/2, h7 14.5/12/8, dd 2.7."""
    R1 = {"cherry": 0.045, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.145, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("ZZZZ", cand_ZZZZ))


def cand_AAAAA():
    """AAAAA: try VV + much more cherry. cherry 5/3.5/2.5, bar1 26/22/18, bar2 9/8/7, bar3 3/2.5/2, h7 14/11.5/7.5, dd 2.7.
    R1 nb = 5+26+9+3+14+2.7+0.4 = 60.1 blank 39.9 ✓."""
    R1 = {"cherry": 0.050, "1bar": 0.26, "2bar": 0.09, "3bar": 0.030,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AAAAA", cand_AAAAA))


def cand_BBBBB():
    """BBBBB: trim h7 deeper. cherry 5/3.5/2.5, bar1 26/22/18, bar2 9/8/7, bar3 3/2.5/2,
    h7 13.5/11/7, dd 2.7. R1 nb = 5+26+9+3+13.5+2.7+0.4 = 59.6 blank 40.4. Lift bar2 R1 → 9.5."""
    R1 = {"cherry": 0.050, "1bar": 0.26, "2bar": 0.095, "3bar": 0.030,
          "high7": 0.135, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.085, "3bar": 0.025,
          "high7": 0.110, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.075, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BBBBB", cand_BBBBB))


def cand_CCCCC():
    """CCCCC: trim cherry + trim h7 + bar2 lift. cherry 4/3/2.5, bar1 26/22/18, bar2 11/10/9,
    bar3 3/2.5/2, h7 13.5/11/7, dd 2.7.
    R1 nb = 4+26+11+3+13.5+2.7+0.4 = 60.6 blank 39.4 ✓."""
    R1 = {"cherry": 0.040, "1bar": 0.26, "2bar": 0.11, "3bar": 0.030,
          "high7": 0.135, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.110, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.09, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CCCCC", cand_CCCCC))


def cand_DDDDD():
    """DDDDD: extreme bar2 + low h7. cherry 4/3/2.5, bar1 25/21/17, bar2 12/11/10, bar3 3/2.5/2,
    h7 13.5/11/7, dd 2.7. R1 nb = 4+25+12+3+13.5+2.7+0.4 = 60.6 blank 39.4 ✓."""
    R1 = {"cherry": 0.040, "1bar": 0.25, "2bar": 0.12, "3bar": 0.030,
          "high7": 0.135, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.21, "2bar": 0.11, "3bar": 0.025,
          "high7": 0.110, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.17, "2bar": 0.10, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DDDDD", cand_DDDDD))


def cand_EEEEE():
    """EEEEE: bar1 24/20/16.5, bar2 12/11/10, bar3 3/2.5/2, cherry 4/3/2.5, h7 14/11.5/7.5, dd 2.7.
    R1 nb = 4+24+12+3+14+2.7+0.4 = 60.1 blank 39.9 ✓."""
    R1 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.12, "3bar": 0.030,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.11, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.165, "2bar": 0.10, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EEEEE", cand_EEEEE))


# Wave 9 — VVVV is closest, fails g15 by 0.27pp only.
# VVVV = PPP + cherry R3 +1 (3.5 vs PPP's 2.5).
# To reduce g15 ~0.3pp: cut cherry on a reel by ~0.5pp.
def cand_FFFFF():
    """FFFFF: VVVV − cherry R3 3.5→3.0. R3 nb drops 0.5 → blank rises 0.5 → R3 blank from 58.2→58.7. ok."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FFFFF", cand_FFFFF))


def cand_GGGGG():
    """GGGGG: VVVV − cherry R2 3.5→3.0. compensate density with bar2 R2 6→6.5."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.24, "2bar": 0.065, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GGGGG", cand_GGGGG))


def cand_HHHHH():
    """HHHHH: VVVV − cherry R1 4.5→4.0. R1 nb drops 0.5 → blank rises 0.5 → 40.2 (out of cap).
    compensate bar2 R1 7→7.5."""
    R1 = {"cherry": 0.040, "1bar": 0.28, "2bar": 0.075, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HHHHH", cand_HHHHH))


def cand_IIIII():
    """IIIII: VVVV − bar2/bar3 trim. cherry 4.5/3.5/3.5, bar1 28/24/20, bar2 6.5/5.5/4.5, bar3 1.5/1.3/1,
    h7 16/13/9, dd 2.4. R1 nb = 4.5+28+6.5+1.5+16+2.4+0.4 = 59.3 → blank 40.7 over. Lift cherry R1 → 5.
    R1 nb 59.8 still 40.2 over. Lift h7 → 16.5.
    R1 nb 60.3 blank 39.7 ✓."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.065, "3bar": 0.015,
          "high7": 0.165, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.055, "3bar": 0.013,
          "high7": 0.135, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.045, "3bar": 0.010,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("IIIII", cand_IIIII))


def cand_JJJJJ():
    """JJJJJ: VVVV − cherry R1 4.5→4.2 + R3 3.5→3.2. compensate bar2 R1 7→7.3 + R3 5→5.3."""
    R1 = {"cherry": 0.042, "1bar": 0.28, "2bar": 0.073, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.032, "1bar": 0.20, "2bar": 0.053, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJJJJ", cand_JJJJJ))


def cand_KKKKK():
    """KKKKK: VVVV − bar3 hard trim to 1.2/1/0.8 (drops bar_mixed_pure ~1pp). compensate bar2 +0.8."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.078, "3bar": 0.012,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.068, "3bar": 0.010,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.058, "3bar": 0.008,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KKKKK", cand_KKKKK))


def cand_LLLLL():
    """LLLLL: VVVV − cherry distribution shift. cherry 4/3.5/3.5, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5,
    h7 16/13/9, dd 2.4. R1 nb = 4+28+7+2+16+2.4+0.4 = 59.8 blank 40.2 over. Lift bar2 R1 → 7.5.
    R1 nb 60.3 blank 39.7."""
    R1 = {"cherry": 0.040, "1bar": 0.28, "2bar": 0.075, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.060, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LLLLL", cand_LLLLL))


# Wave 10 — PPP is the best (g15 in cap; only fails g50100 by 0.26pp).
# Trim h7 R2 to drop g50100. R2 blank will rise but stays under R3 blank.
def cand_PPP_v1():
    """PPP + h7 R2 13→12.5. R2 nb drops 0.5pp → R2 blank 49.4. ✓ (still under R3 58.2)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v1", cand_PPP_v1))


def cand_PPP_v2():
    """PPP + h7 R1 16→15.5 + h7 R2 13→12.5. R1 nb 59.8 blank 40.2 over."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v2", cand_PPP_v2))


def cand_PPP_v3():
    """PPP_v1 + R1 cherry +0.5 (to keep R1 blank 39.7), and trim h7 R3 9→8.5."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.155, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v3", cand_PPP_v3))


def cand_PPP_v4():
    """PPP + h7 across all reels reduced: 15/12/8. R1 nb = 4.5+28+7+2+15+2.4+0.4 = 59.3.
    Lift cherry R1 → 5 (g15 risk). R1 nb 59.8 blank 40.2 over. Lift bar2 R1 → 7.5.
    R1 nb 60.3 blank 39.7 ✓."""
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.075, "3bar": 0.020,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v4", cand_PPP_v4))


def cand_PPP_v5():
    """PPP-base + h7 R2 trim 13→12.3 only. R2 nb drops 0.7 → blank 49.6."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.123, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.090, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v5", cand_PPP_v5))


def cand_PPP_v6():
    """PPP-base + h7 R3 9→8 only. R3 nb drops 1pp → blank 59.2."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v6", cand_PPP_v6))


def cand_PPP_v7():
    """PPP-base − h7 R2 13→12 AND R3 9→8.5. Both trims for g50100 ≤ 27."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v7", cand_PPP_v7))


# Wave 11 — PPP_v7 is VERY close. Only fails total_rtp by 0.16pp under floor.
# Add small bump to h7 R1 to lift base RTP by 0.2pp. h7 R1 16 → 16.3.
def cand_PPP_v8():
    """PPP_v7 + h7 R1 16→16.4. R1 nb = 4.5+28+7+2+16.4+2.4+0.4 = 60.7 blank 39.3 ✓."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.164, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v8", cand_PPP_v8))


def cand_PPP_v9():
    """PPP_v7 + bar1 R1 +0.5 to lift base RTP. R1 nb +0.5 → blank 39.2."""
    R1 = {"cherry": 0.045, "1bar": 0.285, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v9", cand_PPP_v9))


def cand_PPP_v10():
    """PPP_v7 + cherry R3 2.5→3 (lift RTP slightly via cherry-1, marginal g15 impact)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v10", cand_PPP_v10))


def cand_PPP_v11():
    """PPP_v7 + h7 R3 8.5→9.5 (R3 only). R3 nb +1 → blank 57.7."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.095, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v11", cand_PPP_v11))


def cand_PPP_v12():
    """PPP_v7 + bar2 R3 5→6 (lift bar2 share)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.06, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v12", cand_PPP_v12))


def cand_PPP_v13():
    """PPP_v7 + R2 h7 12→12.2. R2 nb +0.2 → blank 49.7."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.122, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v13", cand_PPP_v13))


def cand_PPP_v14():
    """PPP_v7 + cherry R2 3.5→4 + R3 2.5→3.5."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v14", cand_PPP_v14))


def cand_PPP_v15():
    """PPP_v7 + dd R3 2.4→2.6 (small cadence shift, marginal RTP via wild_pure)."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v15", cand_PPP_v15))


def cand_PPP_v16():
    """PPP_v7 + bar1 R2 +0.5. lifts base RTP via bar1_pure."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.245, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v16", cand_PPP_v16))


# Wave 12 — PPP_v10 passes all 14 hardlines but bar2/bar3 share < 5% / high7 > 30%.
# Try to lift bar2/bar3 to reduce high7 share. bar2/bar3 mostly drive bar_mixed_pure (g15).
def cand_PPP_v17():
    """PPP_v10 + bar2 8 across reels (lift 1pp from 7/6/5 base). compensate h7 down 1.5pp.
    R1 nb = 4.5+28+8+2+14.5+2.4+0.4 = 59.8 blank 40.2 just over. Lift cherry +0.3."""
    R1 = {"cherry": 0.048, "1bar": 0.28, "2bar": 0.080, "3bar": 0.020,
          "high7": 0.145, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.038, "1bar": 0.24, "2bar": 0.070, "3bar": 0.018,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.060, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v17", cand_PPP_v17))


def cand_PPP_v18():
    """PPP_v10 + bar3 trip (2→3, 1.8→2.5, 1.5→2). compensate h7 down."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v18", cand_PPP_v18))


def cand_PPP_v19():
    """PPP_v10 final tune: cherry 4.5/3.5/3, bar1 28/24/20, bar2 7/6/5, bar3 2/1.8/1.5, h7 16/12.5/8.5, dd 2.4.
    Should be PPP_v7 + cherry R3 +0.5. Very close to PPP_v10 but cherry tweak."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.125, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v19", cand_PPP_v19))


def cand_PPP_v20():
    """PPP_v10 + dd 2.4 → 2.5 (cadence 1/66k stays in band). Marginal RTP boost via wild_pure."""
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.160, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.24, "2bar": 0.06, "3bar": 0.018,
          "high7": 0.120, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_v20", cand_PPP_v20))


def main():
    strips = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    passes = []
    near_passes = []
    for name, fn in CANDIDATES:
        try:
            margs = fn()
            r = evaluate(margs)
            ok, summary = report(name, r, strips=strips, verbose=True)
            if ok:
                passes.append((name, r))
            elif summary["n_fail"] <= 1 and not summary["family_violations"]:
                near_passes.append((name, r, summary))
        except Exception as e:
            print(f"\n======== Candidate: {name} ERROR ========")
            print(f"  {type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print(f"TOTAL FULL-PASS candidates: {len(passes)}")
    for name, r in passes:
        g15 = r["session_bucket"].get("ge1_lt5", 0)
        b1 = r["family_shares"].get("bar1", 0)
        print(f"  {name:8s} total_rtp={r['total_rtp']:7.3f}  g15={g15:6.3f}  bar1_share={b1:6.2f}%  cadence=1/{r['wild_cadence']:.0f}")

    print(f"\nNear-pass (≤1 hardline fail, no family violation): {len(near_passes)}")
    for name, r, s in near_passes:
        g15 = r["session_bucket"].get("ge1_lt5", 0)
        b1 = r["family_shares"].get("bar1", 0)
        print(f"  {name:8s} n_fail={s['n_fail']}  g15={g15:6.3f}  bar1={b1:6.2f}%  cadence_ok={s['cadence_ok']} rtp_safe={s['rtp_safe']}")


if __name__ == "__main__":
    main()
