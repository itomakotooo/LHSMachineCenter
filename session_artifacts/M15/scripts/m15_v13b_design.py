"""M15 v13b mode 1 — Designer candidate generator under v6 hardlines.

USER_HARDLINES.md v6 changes vs v5:
  - DROPPED: strict bell-shape peak (5-15×)
  - ADDED:   g15 must NOT be max(g15, g510, g1020) — softer direction

V/X review of FINAL_E rejected it because pushing bar1 to 34/30/25%
created total pareto collapse (bar1 41.9% share, bar2/bar3/cherry small
pays effectively dead, wild_pure cadence 1/158k, dd PWDF 25.5%).

v13b design objective (per main session iteration brief):
  - PASS all 14 hardlines + g15 < max(g510, g1020)
  - target per-family share: each in 5%-25% of base RTP
  - wild_pure cadence in [1/100k, 1/50k] (dd cube ≥ 1e-5)
  - dd PWDF achievable ≥ 28%  (needs higher dd marginal — ~2.4-3.0%)
  - RTP > 94.5pp (safety vs sampling noise)

Strategy hints (more balanced than FINAL_E):
  - cherry 3-5% per reel (more cherry-2/cherry-3 visibility)
  - bar1 18-22% per reel (less dominant)
  - bar2 10-14% per reel (bar_mixed engine, contributes g15 + g1020)
  - bar3 5-8% per reel (visible, contributes bar_mixed + bar3_pure g2050)
  - high7 7-10% per reel (classic seven density)
  - dd 2.5-3.5% per reel (wild_pure cadence + dd PWDF)
  - jp ≤ 0.5% per reel
  - td R3 ≈ 0.011 (locked feature trigger)
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
    analytic_profile,
    analytic_profile_from_marginals,
    compute_reel_marginal,
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

# Precompute feature per-bucket EV (constant — feature_params locked)
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


def to_bucket(r: float) -> str | None:
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


# pay_id -> family map for share-of-base computation
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


def make_marginals(R1: dict, R2: dict, R3: dict) -> list[dict[str, float]]:
    """Add blank residual and normalize each reel to sum to 1."""
    out = []
    for R in (R1, R2, R3):
        R = dict(R)
        non_blank = sum(R.values())
        R["blank"] = max(0.001, 1.0 - non_blank)
        s = sum(R.values())
        out.append({k: v / s for k, v in R.items() if v > 0})
    return out


def evaluate(margs: list[dict[str, float]]) -> dict:
    """Run analytic_profile_from_marginals + add feature + family shares."""
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

    # Family share-of-base
    pay_rtp = prof["pay_rtp"]  # fractional, e.g. 0.0866 = 8.66pp
    family_pp = defaultdict(float)
    for pid, rtp in pay_rtp.items():
        fam = PAY_FAM_MAP.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp * 100  # in pp
    # combine high7 wild + pure for share-of-base check
    high7_combined_pp = family_pp.get("high7_wild", 0) + family_pp.get("high7_pure", 0)
    family_shares = {}
    if base_rtp > 0:
        family_shares["cherry1"] = family_pp.get("cherry1", 0) / base_rtp * 100
        family_shares["cherry2"] = family_pp.get("cherry2", 0) / base_rtp * 100
        family_shares["cherry3"] = family_pp.get("cherry3", 0) / base_rtp * 100
        family_shares["bar1"] = family_pp.get("bar1", 0) / base_rtp * 100
        family_shares["bar2"] = family_pp.get("bar2", 0) / base_rtp * 100
        family_shares["bar3"] = family_pp.get("bar3", 0) / base_rtp * 100
        family_shares["bar_mixed"] = family_pp.get("bar_mixed", 0) / base_rtp * 100
        family_shares["high7"] = high7_combined_pp / base_rtp * 100
        family_shares["wild_pure"] = family_pp.get("wild_pure", 0) / base_rtp * 100
    # wild_pure cadence
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


def check14(r: dict) -> list[tuple[str, float, str, tuple]]:
    """Return list of (name, value, status, (lo, hi)) for all 14 hardlines."""
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


def check_v6_direction(r: dict) -> tuple[bool, str]:
    """v6 softer direction: g15 NOT the max of {g15, g510, g1020}."""
    s = r["session_bucket"]
    g15 = s.get("ge1_lt5", 0)
    g510 = s.get("ge5_lt10", 0)
    g1020 = s.get("ge10_lt20", 0)
    # g15 must be strictly less than max(g510, g1020) ideally;
    # at minimum g15 must not be unique max.
    direction_ok = g15 < max(g510, g1020)
    if direction_ok:
        if g510 >= g1020:
            peak = f"g510 leads (g510={g510:.2f}, g15={g15:.2f}, gap +{g510-g15:.2f}pp)"
        else:
            peak = f"g1020 leads (g1020={g1020:.2f}, g15={g15:.2f}, gap +{g1020-g15:.2f}pp)"
    else:
        peak = f"g15 dominant (g15={g15:.2f}, g510={g510:.2f}, g1020={g1020:.2f}) — VIOLATION"
    return direction_ok, peak


def report(name: str, r: dict, verbose: bool = True) -> tuple[bool, dict]:
    """Returns (overall_pass, summary). overall_pass requires all 14 hardlines
    AND v6 direction AND family shares within target [5, 25] AND wild cadence
    in [1/100k, 1/50k] AND total_rtp ≥ 94.5 for noise safety."""
    checks = check14(r)
    direction_ok, peak = check_v6_direction(r)
    n_fail = sum(1 for _, _, st, _ in checks if st == "FAIL")
    # additional design objectives
    fs = r["family_shares"]
    # we EXCLUDE cherry2, cherry3 (too small to ever reach 5%), and wild_pure (its share is small but cadence matters)
    KEY_FAMILIES = ["cherry1", "bar1", "bar2", "bar3", "bar_mixed", "high7"]
    family_violations = []
    for fam in KEY_FAMILIES:
        v = fs.get(fam, 0)
        if v < 5.0:
            family_violations.append((fam, v, "below 5%"))
        elif v > 25.0:
            family_violations.append((fam, v, "above 25%"))
    cadence_ok = 50000 <= r["wild_cadence"] <= 100000
    rtp_safe = r["total_rtp"] >= 94.5
    if verbose:
        print(f"\n======== Candidate: {name} ========")
        print(f"  total_rtp={r['total_rtp']:.3f}pp  hit_session={r['hit_session']:.3f}%")
        print(f"  base_rtp={r['base_rtp']:.3f}pp  feature_rtp={r['feature_rtp']:.3f}pp  "
              f"(split {r['base_rtp']/r['total_rtp']*100:.0f}:{r['feature_rtp']/r['total_rtp']*100:.0f})")
        print(f"  R1_blank={r['r1_blank']:.3f}%  R2_blank={r['r2_blank']:.3f}%  R3_blank={r['r3_blank']:.3f}%")
        print(f"  trigger={r['trigger']:.3f}%  wild_cadence=1/{r['wild_cadence']:.0f}")
        s = r["session_bucket"]
        g15 = s.get("ge1_lt5", 0)
        g510 = s.get("ge5_lt10", 0)
        g1020 = s.get("ge10_lt20", 0)
        print(f"  Buckets: g15={g15:.3f}  g510={g510:.3f}  g1020={g1020:.3f}  "
              f"g2050={s.get('ge20_lt50',0):.3f}  g50100={s.get('ge50_lt100',0):.3f}  "
              f"g100200={s.get('ge100_lt200',0):.3f}  g200500={s.get('ge200_lt500',0):.3f}")
        print(f"  v6 direction: {peak}")
        print(f"  Family shares-of-base:")
        for fam, share in r["family_shares"].items():
            print(f"    {fam:12s} {share:6.2f}%   ({r['family_pp'].get(fam, 0) if fam != 'high7' else r['high7_combined_pp']:.2f}pp)")
        if family_violations:
            print(f"  Family violations: {family_violations}")
        if not cadence_ok:
            print(f"  Wild cadence OUT OF BAND [1/100k, 1/50k]: 1/{r['wild_cadence']:.0f}")
        if not rtp_safe:
            print(f"  RTP safety margin: total_rtp={r['total_rtp']:.3f} < 94.5pp")
        if n_fail > 0:
            print(f"  Hardline fails: {n_fail}/14")
            for nm, val, st, (lo, hi) in checks:
                if st == "FAIL":
                    print(f"    FAIL {nm:18s} = {val:8.3f}  target [{lo}, {hi}]")
    overall_pass = (n_fail == 0 and direction_ok and not family_violations and cadence_ok and rtp_safe)
    return overall_pass, {
        "checks": checks,
        "direction_ok": direction_ok,
        "peak": peak,
        "n_fail": n_fail,
        "family_violations": family_violations,
        "cadence_ok": cadence_ok,
        "rtp_safe": rtp_safe,
        "r": r,
    }


# -----------------------------------------------------------------------
# Candidates — balanced design exploration (v6 direction + family balance)
# -----------------------------------------------------------------------
# Strategy: cherry 3-5%, bar1 18-22%, bar2 10-14%, bar3 5-8%, h7 7-10%, dd 2.5-3.5%
# Goal: keep g15 in band but ensure g510/g1020 > g15, family share in [5, 25],
#       wild cadence in [50k, 100k], total_rtp ≥ 94.5pp.
CANDIDATES: list[tuple[str, callable]] = []


def cand_a_balanced():
    """Baseline: cherry 4/3.5/3, bar1 20/18/16, bar2 12/12/12, bar3 6/6/6, h7 9/8/6, dd 3/3/2.5."""
    R1 = {"cherry": 0.040, "1bar": 0.20, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.090, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("A_balanced", cand_a_balanced))


def cand_b_lower_bar1():
    """B: lower bar1 to 18/17/15, lift bar2 to 13."""
    R1 = {"cherry": 0.040, "1bar": 0.18, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.090, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.060, "doublediamond": 0.027, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("B_lower_bar1", cand_b_lower_bar1))


def cand_c_higher_dd():
    """C: lift dd to 3.5/3.5/2.8 to fix wild cadence (and prep PWDF)."""
    R1 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.060, "doublediamond": 0.028, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("C_higher_dd", cand_c_higher_dd))


def cand_d_bar2_heavy():
    """D: 2bar heavy (push g1020 from bar2_pure 10×)."""
    R1 = {"cherry": 0.040, "1bar": 0.18, "2bar": 0.14, "3bar": 0.06,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.14, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.14, "3bar": 0.06,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("D_bar2_heavy", cand_d_bar2_heavy))


def cand_e_lower_cherry():
    """E: lower cherry 3/2.5/2 to drop g15 cherry contribution."""
    R1 = {"cherry": 0.030, "1bar": 0.21, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.090, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.19, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("E_lower_cherry", cand_e_lower_cherry))


def cand_f_dd_3pct():
    """F: dd 3.0% uniform — push cadence into band  (3% cubed = 2.7e-5 → 1/37k, too freq!).
       So we'll use 2.5% uniform → cube 1.56e-5 → 1/64k (in band)."""
    R1 = {"cherry": 0.040, "1bar": 0.20, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.085, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("F_dd25pct", cand_f_dd_3pct))


def cand_g_bar1_heavy_balanced():
    """G: bar1 22/20/18 (more than v9 but balanced), 2bar 12, dd 2.5."""
    R1 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.12, "3bar": 0.055,
          "high7": 0.085, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.20, "2bar": 0.12, "3bar": 0.055,
          "high7": 0.080, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.12, "3bar": 0.055,
          "high7": 0.060, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("G_bar1_22", cand_g_bar1_heavy_balanced))


def cand_h_higher_high7():
    """H: high7 11/10/8 — lift mid-tier brand."""
    R1 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.110, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.100, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.080, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("H_higher_h7", cand_h_higher_high7))


def cand_i_lower_bar1_lower_bar3():
    """I: bar1 17, bar3 4 — drop bar_mixed_pure RTP."""
    R1 = {"cherry": 0.040, "1bar": 0.17, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.095, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.085, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.14, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.065, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("I_bar1_17_bar3_4", cand_i_lower_bar1_lower_bar3))


def cand_j_asymmetric_dd():
    """J: asymmetric dd 3.5/3.0/2.0 to lift PWDF on R1 while keeping cadence in band.
       3.5 × 3.0 × 2.0 = 2.1e-5 → 1/48k (just in band).
    """
    R1 = {"cherry": 0.040, "1bar": 0.20, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.055, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("J_asym_dd35_30_20", cand_j_asymmetric_dd))


def cand_k_low_blank_R1():
    """K: R1 blank ~32% (winners-friendly extreme), more cherry + h7 lift R1."""
    R1 = {"cherry": 0.045, "1bar": 0.21, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.110, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.12, "3bar": 0.06,
          "high7": 0.065, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("K_low_blank_R1", cand_k_low_blank_R1))


def cand_l_balanced_v2():
    """L: balanced revision after looking at early results. Target: bar1 19/17/15,
       bar2 12, bar3 5, cherry 3.5/3/2.5, h7 8/7/6, dd 3/3/2.5."""
    R1 = {"cherry": 0.035, "1bar": 0.19, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.070, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.15, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("L_balanced_v2", cand_l_balanced_v2))


def cand_m_classic_archetype():
    """M: classic archetype balance — closer to RWB / Top Dollar:
       cherry 4/3.5/3, bar1 19/17/15, bar2 13/12/11, bar3 5/5/4, h7 8/7/5, dd 2.7/2.7/2.4.
       2.7^2 * 2.4 = 1.75e-5 → 1/57k (in band)
    """
    R1 = {"cherry": 0.040, "1bar": 0.19, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.070, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.11, "3bar": 0.04,
          "high7": 0.050, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("M_archetype", cand_m_classic_archetype))


def cand_n_classic_v2():
    """N: similar to M but lower cherry, more 1bar (bell tilt to g510)."""
    R1 = {"cherry": 0.030, "1bar": 0.21, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.085, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.19, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.075, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.11, "3bar": 0.04,
          "high7": 0.055, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("N_lower_cherry_higher_bar1", cand_n_classic_v2))


def cand_o_dd28():
    """O: dd uniform 2.8% (cadence 2.8^3 = 2.2e-5 → 1/46k — borderline)
       Adjust to dd 2.7/2.7/2.6 → 1.89e-5 → 1/53k.
    """
    R1 = {"cherry": 0.035, "1bar": 0.19, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.17, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.070, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.15, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.050, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("O_dd_2.7uniform", cand_o_dd28))


def cand_p_tight_g15():
    """P: tighter g15 — drop cherry to 3% uniform, bar3 to 4%."""
    R1 = {"cherry": 0.030, "1bar": 0.20, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.085, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.075, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.16, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("P_tight_g15", cand_p_tight_g15))


def cand_q_v9_balance_dd_lift():
    """Q: similar to v9 family balance but lift dd to fix cadence + lower bar3 to fix g15.
       v9 had: cherry 5/5/2.5 / bar1 13.8/12.8/14.8 / bar2 13.5/12.5/14.5 / bar3 8.8/7.1/9.5
              / h7 ~2-3 / dd 2.5/3/1.5.
       v9 failed v6 g15 cap @22pp because cherry-1 + bar_mixed too high.
       Try: cherry 3.5/3/2.5 (lower!), bar1 17, bar2 12, bar3 5 (lower!), h7 8, dd 2.7.
    """
    R1 = {"cherry": 0.035, "1bar": 0.17, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.075, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("Q_v9_balance_dd_lift", cand_q_v9_balance_dd_lift))


def cand_r_v9_dropbar1():
    """R: like Q but lower bar1 16/15/13 and lift 2bar 13."""
    R1 = {"cherry": 0.035, "1bar": 0.16, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.15, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.075, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.13, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("R_lower_bar1_higher_bar2", cand_r_v9_dropbar1))


def cand_s_asymmetric_v6():
    """S: asymmetric — R1 winners-friendly densities, R3 sparse:
       R1: cherry 4, bar1 22, bar2 13, bar3 6, h7 10, dd 3
       R2: cherry 3, bar1 18, bar2 12, bar3 5, h7 8, dd 3
       R3: cherry 2, bar1 14, bar2 11, bar3 4, h7 6, dd 2.5
    """
    R1 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.100, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.18, "2bar": 0.12, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.14, "2bar": 0.11, "3bar": 0.04,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("S_asymmetric", cand_s_asymmetric_v6))


def cand_t_low_g15_focus():
    """T: design objective — minimize g15 while preserving family balance.
       Lower cherry (2.5%) + lower bar3 (4%) + standard rest.
    """
    R1 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.16, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("T_low_g15", cand_t_low_g15_focus))


# -----------------------------------------------------------------------
# Round 2 candidates — after seeing R1 blank too high and g15 dominant
# Need: R1 non-blank ≥ 65% (R1 blank ≤ 35%)
#       Lower cherry to break cherry-1 dominance in g15
#       Higher 1bar/2bar to lift g510 & g1020
# -----------------------------------------------------------------------

def cand_u_high_density_low_cherry():
    """U: dense R1, very low cherry (1.5%) → cherry-1 hit ~4-5% only.
       bar1 25/22/19, bar2 13, bar3 5, h7 12, dd 3.
       R1 non-blank: 1.5 + 25 + 13 + 5 + 12 + 3 + 0.4 = 59.9 + R2 td = R1 blank ~40.
    """
    R1 = {"cherry": 0.015, "1bar": 0.25, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.22, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.100, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.012, "1bar": 0.19, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.075, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("U_high_density_low_cherry", cand_u_high_density_low_cherry))


def cand_v_dense_R1_h7():
    """V: similar but lift R1 further. cherry 2/1.5/1.2, bar1 24/22/18, bar2 13, bar3 5,
       h7 14/12/8, dd 3.
       R1 non-blank: 2 + 24 + 13 + 5 + 14 + 3 + 0.4 = 61.4 → R1 blank 38.6
    """
    R1 = {"cherry": 0.020, "1bar": 0.24, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.140, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.22, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.012, "1bar": 0.18, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("V_dense_R1", cand_v_dense_R1_h7))


def cand_w_focus_bar2():
    """W: 1bar moderate (20/18/16), 2bar HIGH (15/15/14) → g1020 should peak.
       cherry 2.5/2/1.5 (low to limit g15).
       R1 non-blank: 2.5 + 20 + 15 + 5 + 12 + 3 + 0.4 = 57.9
    """
    R1 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.15, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.18, "2bar": 0.15, "3bar": 0.05,
          "high7": 0.100, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.16, "2bar": 0.14, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("W_2bar_peak", cand_w_focus_bar2))


def cand_x_bar2_dominant_lower_h7():
    """X: 2bar high (15), 1bar 18 — g1020 peak; cherry 2/2/1.5; h7 9; dd 2.8.
       R1 non-blank: 2 + 18 + 15 + 5 + 9 + 2.8 + 0.4 = 52.2 → R1 blank 47.8 (still high)
       Need more density. Add more bar3, lift cherry slightly: cherry 2.5, bar3 6, h7 12.
       R1 non-blank: 2.5 + 18 + 15 + 6 + 12 + 2.8 + 0.4 = 56.7 → R1 blank 43 (still high)
    """
    R1 = {"cherry": 0.025, "1bar": 0.18, "2bar": 0.15, "3bar": 0.06,
          "high7": 0.120, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.15, "3bar": 0.06,
          "high7": 0.100, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.15, "2bar": 0.14, "3bar": 0.05,
          "high7": 0.075, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("X_bar2_dominant", cand_x_bar2_dominant_lower_h7))


def cand_y_very_dense_R1():
    """Y: very dense R1 (non-blank 70%, blank 30%).
       cherry 3, bar1 23, bar2 14, bar3 6, h7 18, dd 5, jp 0.4.
       3+23+14+6+18+5+0.4 = 69.4 → R1 blank 30.6.
       But dd 5% × 5 × 4 = 100e-6 → 1/10k — too freq, breaks band [50k, 100k]
       So lower dd to 3, and need 100% sum still.
       Try: cherry 2.5, bar1 22, bar2 13, bar3 6, h7 18, dd 3, jp 0.4 = 64.9
       R1 blank 35.1 — better but still need more.
       cherry 3, bar1 22, bar2 15, bar3 6, h7 15, dd 3, jp 0.4 = 64.4 — same range
    """
    R1 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.14, "3bar": 0.06,
          "high7": 0.150, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.13, "3bar": 0.06,
          "high7": 0.120, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("Y_dense_R1_h7", cand_y_very_dense_R1))


def cand_z_dense_low_cherry():
    """Z: maximize density, ultra-low cherry. Target R1 blank 32-36.
       cherry 1.2/1.0/0.8, bar1 25/22/18, bar2 14/13/12, bar3 5/5/4, h7 18/15/10, dd 3/3/2.5, jp 0.4
       R1: 1.2 + 25 + 14 + 5 + 18 + 3 + 0.4 = 66.6 → R1 blank 33.4
    """
    R1 = {"cherry": 0.012, "1bar": 0.25, "2bar": 0.14, "3bar": 0.05,
          "high7": 0.180, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.010, "1bar": 0.22, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.150, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.008, "1bar": 0.18, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.100, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("Z_dense_low_cherry", cand_z_dense_low_cherry))


def cand_aa_extreme_h7():
    """AA: high7 dominant R1 to fill density.
       cherry 2.5, bar1 20, bar2 13, bar3 5, h7 20, dd 3.
       R1: 2.5 + 20 + 13 + 5 + 20 + 3 + 0.4 = 63.9 → R1 blank 36.1
    """
    R1 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.200, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.18, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.150, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.16, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.090, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AA_high_h7", cand_aa_extreme_h7))


def cand_bb_balanced_dense():
    """BB: balanced, density-focused. cherry 2.5, bar1 22, bar2 13, bar3 5, h7 14, dd 3.
       R1: 2.5+22+13+5+14+3+0.4 = 59.9 → R1 blank 40.1 (just over!) need 1 more.
       Add: cherry 3, h7 15 → 3+22+13+5+15+3+0.4 = 61.4 → R1 blank 38.6
    """
    R1 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.150, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.120, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BB_balanced_dense", cand_bb_balanced_dense))


def cand_cc_low_cherry_high_h7():
    """CC: cherry 1.8, bar1 22, bar2 13, bar3 5, h7 16, dd 3.
       R1: 1.8+22+13+5+16+3+0.4 = 61.2 → R1 blank 38.8
    """
    R1 = {"cherry": 0.018, "1bar": 0.22, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.160, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.20, "2bar": 0.13, "3bar": 0.05,
          "high7": 0.130, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.012, "1bar": 0.17, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CC_low_cherry_h7", cand_cc_low_cherry_high_h7))


def cand_dd_dense_bar2_focus():
    """DD: 2bar slightly elevated (14) + lower bar1 (19) + h7 16.
       cherry 2 to keep g15 contribution moderate.
       R1: 2+19+14+5+16+3+0.4 = 59.4 → R1 blank 40.6 (just over)
       Add cherry 2.5: 60.4 → R1 blank 39.6
    """
    R1 = {"cherry": 0.025, "1bar": 0.19, "2bar": 0.14, "3bar": 0.05,
          "high7": 0.160, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.14, "3bar": 0.05,
          "high7": 0.130, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.15, "2bar": 0.13, "3bar": 0.04,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DD_bar2_dense", cand_dd_dense_bar2_focus))


def cand_ee_g510_dominant_balanced():
    """EE: push bar1 high (25/22/18) for g510 lead, but bar3 only 4 to limit bar_mixed.
       cherry 2, h7 14, dd 3.
       R1: 2+25+12+4+14+3+0.4 = 60.4 → R1 blank 39.6
    """
    R1 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.140, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.22, "2bar": 0.12, "3bar": 0.04,
          "high7": 0.110, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.012, "1bar": 0.18, "2bar": 0.11, "3bar": 0.04,
          "high7": 0.075, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EE_g510_dom_balanced", cand_ee_g510_dominant_balanced))


# -----------------------------------------------------------------------
# Round 3 candidates — structural insight:
#   - bar_mixed inflation when bar2 AND bar3 both ≥ 5%
#   - FINAL_E had bar2=4.5, bar3=1.2 (small bar_mixed)
#   - To balance: need bar2 + bar3 small total but not zero
#   - cherry 3% on R1 to keep cherry-2/3 visible
# -----------------------------------------------------------------------

def cand_ff_final_e_inspired_softer():
    """FF: like FINAL_E but slightly more balanced.
       cherry 4/3/2.5 (more), bar1 25/22/19 (less than FINAL_E 34/30/25),
       bar2 6/6/5.5 (more than FINAL_E 4.5), bar3 3/3/2.5 (more than 1.2),
       h7 12/10/7, dd 2.8/2.8/2.5.
       R1: 4+25+6+3+12+2.8+0.4 = 53.2 → R1 blank 46.8 (still too high)
       Add more density: bar1 28, h7 14 → 4+28+6+3+14+2.8+0.4 = 58.2 → 41.8 blank
       More: bar1 30 → 60.2 → 39.8 (in band!)
    """
    R1 = {"cherry": 0.040, "1bar": 0.30, "2bar": 0.06, "3bar": 0.03,
          "high7": 0.140, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.27, "2bar": 0.06, "3bar": 0.03,
          "high7": 0.110, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.22, "2bar": 0.055, "3bar": 0.025,
          "high7": 0.075, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FF_final_e_softer", cand_ff_final_e_inspired_softer))


def cand_gg_lower_bar2_3():
    """GG: bar2 5, bar3 2 (very low, FINAL_E direction) but more cherry + h7 for density.
       bar1 28/25/22, cherry 4/3.5/3, h7 13/11/8.
       R1: 4+28+5+2+13+2.8+0.4 = 55.2 → blank 44.8 (still high)
       Add: h7 15 → 57.2 → 42.8
       Add: bar1 30 → 59.2 → 40.8
       Add: cherry 5 → 60.2 → 39.8
    """
    R1 = {"cherry": 0.050, "1bar": 0.30, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.150, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.27, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.120, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.045, "3bar": 0.02,
          "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GG_low_bar23_dense", cand_gg_lower_bar2_3))


def cand_hh_balanced_4_4():
    """HH: split bars more evenly — both bar2 (8) and bar3 (4) but bar1 moderate (20).
       cherry 4, h7 15, dd 3.
       R1: 4+20+8+4+15+3+0.4 = 54.4 → blank 45.6 (high)
       Solution: lift bar1 to 23, h7 16 → 4+23+8+4+16+3+0.4 = 58.4 → blank 41.6
       Lift bar1 25, cherry 5 → 5+25+8+4+16+3+0.4 = 61.4 → blank 38.6
    """
    R1 = {"cherry": 0.050, "1bar": 0.25, "2bar": 0.08, "3bar": 0.04,
          "high7": 0.160, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.22, "2bar": 0.08, "3bar": 0.04,
          "high7": 0.130, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.19, "2bar": 0.07, "3bar": 0.035,
          "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HH_balanced_4_4", cand_hh_balanced_4_4))


def cand_ii_low_cherry_softer():
    """II: cherry 2/1.5/1.2 (LOW), bar2 7, bar3 3, bar1 28/25/21.
       R1: 2+28+7+3+15+3+0.4 = 58.4 → blank 41.6 (still high)
       Add cherry 2.5, h7 17 → 2.5+28+7+3+17+3+0.4 = 60.9 → blank 39.1 ✓
    """
    R1 = {"cherry": 0.025, "1bar": 0.28, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.170, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.130, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.21, "2bar": 0.065, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("II_low_cherry_dense", cand_ii_low_cherry_softer))


def cand_jj_split_balance():
    """JJ: split-cherry approach (cherry 5/3/1.5 — only R1 high)
       to keep R1 cherry density high (winners-friendly) but limit cherry-1 hit by R3.
       cherry-anywhere hit ≈ 1 - 0.95 × 0.97 × 0.985 ≈ 0.0916 → 9.16% (still high)
    """
    R1 = {"cherry": 0.050, "1bar": 0.27, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.140, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.120, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.21, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJ_split_cherry", cand_jj_split_balance))


def cand_kk_bar1_moderate_bar2_5():
    """KK: bar1 23/20/17 (more moderate than FINAL_E), bar2 5, bar3 2,
       cherry 4/3/2 (similar to FINAL_E), h7 15/12/8, dd 3.
       R1: 4+23+5+2+15+3+0.4 = 52.4 → blank 47.6 (high)
       Need more density: cherry 4, h7 17, dd 3 → 4+23+5+2+17+3+0.4 = 54.4 → 45.6
       Need to use bar2_pure for g1020 → keep bar2 at 8 anyway.
    """
    R1 = {"cherry": 0.040, "1bar": 0.23, "2bar": 0.08, "3bar": 0.03,
          "high7": 0.170, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.21, "2bar": 0.08, "3bar": 0.03,
          "high7": 0.140, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.18, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.095, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KK_bar1_23_bar2_8", cand_kk_bar1_moderate_bar2_5))


def cand_ll_dd_28():
    """LL: dd 2.8% (just above wild cadence band lower edge),
       cherry 3.5/3/2.5, bar1 26/23/20, bar2 7, bar3 3, h7 15/13/8.
       2.8^3 = 2.2e-5 → 1/45k (need to lift dd a bit or accept border).
       R1: 3.5+26+7+3+15+2.8+0.4 = 57.7 → blank 42.3
       Need density: h7 17 → 59.7 → 40.3. cherry 4 → 60.2 → 39.8.
    """
    R1 = {"cherry": 0.040, "1bar": 0.26, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.170, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.23, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.140, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.20, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LL_dd28_dense", cand_ll_dd_28))


def cand_mm_dd_25_h7_18():
    """MM: dd 2.5 (lower cadence ~64k), h7 18, balanced bars.
       cherry 3.5, bar1 25, bar2 7, bar3 3 → R1: 3.5+25+7+3+18+2.5+0.4 = 59.4 → 40.6 blank
       lift cherry 4 → 60.4 → 39.6 blank
    """
    R1 = {"cherry": 0.040, "1bar": 0.25, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.07, "3bar": 0.03,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.19, "2bar": 0.065, "3bar": 0.025,
          "high7": 0.090, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("MM_dd25_h718", cand_mm_dd_25_h7_18))


def cand_nn_v9_inspired_shifted():
    """NN: v9 style bars but adjusted — lower bars to limit g15 + push high7 for density.
       cherry 3.5, bar1 18, bar2 10, bar3 4, h7 22, dd 2.5.
       R1: 3.5+18+10+4+22+2.5+0.4 = 60.4 → blank 39.6
       Issue: h7 22 will inflate g2050+ buckets significantly. Test it.
    """
    R1 = {"cherry": 0.035, "1bar": 0.18, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.220, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.16, "2bar": 0.10, "3bar": 0.04,
          "high7": 0.180, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.14, "2bar": 0.095, "3bar": 0.035,
          "high7": 0.100, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("NN_v9_inspired_h722", cand_nn_v9_inspired_shifted))


def cand_oo_dd_27_bal():
    """OO: dd 2.7 (cadence ~1/50k tight), balance everything.
       cherry 4/3/2.5, bar1 23/20/17, bar2 8/8/7, bar3 3.5/3.5/3, h7 17/14/9.
       R1: 4+23+8+3.5+17+2.7+0.4 = 58.6 → blank 41.4 (high)
       Try: bar1 25, h7 17 → 4+25+8+3.5+17+2.7+0.4 = 60.6 → 39.4 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.25, "2bar": 0.08, "3bar": 0.035,
          "high7": 0.170, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.08, "3bar": 0.035,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.19, "2bar": 0.075, "3bar": 0.03,
          "high7": 0.090, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("OO_dd27_bal", cand_oo_dd_27_bal))


def cand_pp_max_density_smaller_h7():
    """PP: high density via bar1 (not h7) — bar1 30/27/22 like FINAL_E softened,
       cherry 4/3/2, bar2 6, bar3 3, h7 11/9/6, dd 2.6.
       R1: 4+30+6+3+11+2.6+0.4 = 57 → blank 43 (high)
       Add density: cherry 5 → 5+30+6+3+13+2.6+0.4 = 60 → 40 (boundary)
       Try: bar1 32 → 62 → 38 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.06, "3bar": 0.03,
          "high7": 0.130, "doublediamond": 0.026, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.06, "3bar": 0.03,
          "high7": 0.100, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.23, "2bar": 0.055, "3bar": 0.025,
          "high7": 0.075, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PP_bar1_dense_h7_low", cand_pp_max_density_smaller_h7))


# -----------------------------------------------------------------------
# Round 4 candidates — get g510 > g15 by pushing 1bar harder
# while reducing g15 via lower cherry + lower bar_mixed
# -----------------------------------------------------------------------

def cand_qq_v13_softer():
    """QQ: closer to FINAL_E but moderate. bar1 30/27/22, cherry 3/2.5/2,
       bar2 5, bar3 2, h7 13/10/7, dd 2.7 (cadence 1/50k tight).
       R1: 3+30+5+2+13+2.7+0.4 = 56.1 → R1 blank 43.9 (high)
       Need: lift bar1 to 33 → 59.1 → 40.9. cherry to 4 → 60.1 → 39.9 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.33, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.130, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.100, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.045, "3bar": 0.02,
          "high7": 0.070, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("QQ_v13_softer", cand_qq_v13_softer))


def cand_rr_v13_minus_bars23():
    """RR: like FINAL_E but reduce bar2 to 3 and bar3 to 1.5 (even less).
       FINAL_E had bar2=4.5/4.5/4.5 and bar3=1.2/1.2/1.2 → bar_mixed 4.36pp.
       Try bar2=3/3/3, bar3=1.5/1.5/1.5 → bar_mixed should drop ~30%.
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.03, "3bar": 0.015,
          "high7": 0.150, "doublediamond": 0.018, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.03, "3bar": 0.015,
          "high7": 0.120, "doublediamond": 0.022, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.03, "3bar": 0.015,
          "high7": 0.080, "doublediamond": 0.016, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("RR_v13_minus_bars23", cand_rr_v13_minus_bars23))


def cand_ss_v13_minus_cherry():
    """SS: like FINAL_E but cherry 3/2/1.5 (less). Should reduce g15 by ~3-4pp.
       FINAL_E had cherry 4/3/2.2 → cherry-1 8.66pp.
       Lower cherry 3/2/1.5: cherry-1 hit ≈ 1 - 0.97×0.98×0.985 ≈ 0.064 → 6.4% → 6.4pp.
    """
    R1 = {"cherry": 0.030, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.150, "doublediamond": 0.018, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.022, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.080, "doublediamond": 0.016, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("SS_v13_lower_cherry", cand_ss_v13_minus_cherry))


def cand_tt_dd_27_v13_softer():
    """TT: dd uniform 2.7% — cadence 1/50k tight; FINAL_E-like but bars softer.
       bar1 28/25/21 (FINAL_E was 34/30/25), cherry 4/3/2.5, bar2 4.5, bar3 1.5,
       h7 14/11/8 dd 2.7.
       R1: 4+28+4.5+1.5+14+2.7+0.4 = 55.1 → blank 44.9 (high)
       Lift bar1 32 → 59.1 → 40.9. lift cherry 5 → 60.1 → 39.9 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.32, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.140, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.28, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.110, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.23, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.075, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("TT_dd27_softer", cand_tt_dd_27_v13_softer))


def cand_uu_v13_exact_bigger_dd():
    """UU: exactly FINAL_E marginals but dd lifted to 2.7 uniform for cadence.
       FINAL_E: cherry 4/3/2.2, bar1 34/30/25, bar2 4.5/4.5/4.5, bar3 1.2/1.2/1.2,
                h7 15/12/8, dd 1.8/2.2/1.6.
       Change dd to 2.7/2.7/2.5.
       Also need R3 sum: 2.2+25+4.5+1.2+8+2.5+1.1+0.3 = 44.8 → blank 55.2
       And R1: 4+34+4.5+1.2+15+2.7+0.4 = 61.8 → blank 38.2 ✓
       So this should pass MOST but possibly bump RTP.
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.150, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("UU_final_e_dd27", cand_uu_v13_exact_bigger_dd))


def cand_vv_drop_bar1_lift_bar2():
    """VV: bar1 25/22/19, bar2 7, bar3 2.5, h7 14, dd 2.7, cherry 3/2.5/2.
       R1: 3+25+7+2.5+14+2.7+0.4 = 54.6 → blank 45.4 (high)
       Lift: cherry 4, h7 16, bar1 27 → 4+27+7+2.5+16+2.7+0.4 = 59.6 → blank 40.4
       Lift bar1 to 28: 60.6 → 39.4 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.28, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.160, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.130, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.21, "2bar": 0.065, "3bar": 0.022,
          "high7": 0.080, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("VV_bar1_28_bar2_7", cand_vv_drop_bar1_lift_bar2))


def cand_ww_bar1_30_low_h7():
    """WW: bar1 30/27/22 (FINAL_E-like), bar2 5, bar3 2, cherry 3.5/2.5/2,
       h7 13/10/7 (lower than FINAL_E 15/12/8), dd 2.7.
       R1: 3.5+30+5+2+13+2.7+0.4 = 56.6 → blank 43.4 (high)
       Need density: lift cherry 5 → 5+30+5+2+15+2.7+0.4 = 60.1 → blank 39.9 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.30, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.150, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.27, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.22, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.075, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("WW_bar1_30_dd27", cand_ww_bar1_30_low_h7))


def cand_xx_bar1_32_minimal_bars():
    """XX: bar1 32/28/23, bar2 3, bar3 1.5, cherry 4/3/2.2, h7 14/11/7, dd 2.7.
       R1: 4+32+3+1.5+14+2.7+0.4 = 57.6 → blank 42.4 (high)
       Lift h7 17 → 60.6 → 39.4 ✓
       But h7 17 might push g2050 too high.
    """
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.03, "3bar": 0.015,
          "high7": 0.170, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.03, "3bar": 0.015,
          "high7": 0.130, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.23, "2bar": 0.03, "3bar": 0.015,
          "high7": 0.075, "doublediamond": 0.026, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("XX_bar1_32_min_bars", cand_xx_bar1_32_minimal_bars))


def cand_yy_higher_dd():
    """YY: dd 3.0 uniform — cadence 1/37k (too freq). 2.7 better.
       FINAL_E + dd 2.7/2.7/2.5 (cadence ~ 1/55k).
    """
    R1 = {"cherry": 0.035, "1bar": 0.33, "2bar": 0.04, "3bar": 0.012,
          "high7": 0.150, "doublediamond": 0.027, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.29, "2bar": 0.04, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.24, "2bar": 0.04, "3bar": 0.012,
          "high7": 0.080, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("YY_v13_dd27_lower_cherry", cand_yy_higher_dd))


def cand_zz_final_e_test():
    """ZZ: exactly v13 FINAL_E marginals — sanity check that we can reproduce.
       cherry 4/3/2.2, bar1 34/30/25, bar2 4.5/4.5/4.5, bar3 1.2/1.2/1.2,
       h7 15/12/8, dd 1.8/2.2/1.6, jp 0.4/0.4/0.3, R3 td 1.1.
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.150, "doublediamond": 0.018, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.022, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.080, "doublediamond": 0.016, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("ZZ_final_e_repro", cand_zz_final_e_test))


# -----------------------------------------------------------------------
# Round 5 — Now we have feasibility for v6 direction. Fine-tune for:
#   - RTP in [94.5, 96]
#   - R1 blank in [30, 40]
#   - wild_pure cadence in [50k, 100k]
#   - family share more balanced (each [5%, 25%])
# -----------------------------------------------------------------------

def cand_aaa_final_e_dd25():
    """AAA: FINAL_E + dd 2.5/2.5/2.3 → cadence ~1/70k. Lower RTP."""
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.080, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AAA_final_e_dd25", cand_aaa_final_e_dd25))


def cand_bbb_final_e_dd24():
    """BBB: FINAL_E + dd 2.4 uniform → cadence ~1/72k."""
    R1 = {"cherry": 0.040, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.145, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.295, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.245, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.075, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BBB_final_e_dd24", cand_bbb_final_e_dd24))


def cand_ccc_balance_dd25():
    """CCC: FINAL_E core but slightly more bar2 (5.5) + bar3 (1.5) for family share,
       dd 2.5 uniform. Cherry 4/3/2.2 like FINAL_E.
    """
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.115, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.075, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CCC_balance_dd25", cand_ccc_balance_dd25))


def cand_ddd_lift_bar2():
    """DDD: bar2 6/6/5 (FINAL_E 4.5 → 6) for higher bar2_pure RTP (g1020 contrib).
       bar1 32/28/23, cherry 4/3/2.2, h7 13/10/7, dd 2.5.
    """
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.06, "3bar": 0.012,
          "high7": 0.130, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.06, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.23, "2bar": 0.05, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DDD_bar2_6", cand_ddd_lift_bar2))


def cand_eee_final_e_minus_h7():
    """EEE: FINAL_E core but lower h7 to reduce RTP. cherry 4/3/2.2,
       bar1 34/30/25, bar2 4.5/4.5/4.5, bar3 1.2/1.2/1.2, h7 12/10/7, dd 2.4.
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EEE_final_e_minus_h7", cand_eee_final_e_minus_h7))


def cand_fff_balance_v2():
    """FFF: try bar1 30/27/22, bar2 5.5/5.5/5, bar3 2/2/2 (more visible),
       cherry 3.5/2.5/2, h7 13/10/7, dd 2.5.
    """
    R1 = {"cherry": 0.035, "1bar": 0.30, "2bar": 0.055, "3bar": 0.020,
          "high7": 0.130, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.27, "2bar": 0.055, "3bar": 0.020,
          "high7": 0.100, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.22, "2bar": 0.050, "3bar": 0.018,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FFF_balance_v2", cand_fff_balance_v2))


def cand_ggg_bar3_lift():
    """GGG: bar3 3 (more visible), bar2 5, bar1 30, cherry 4/3/2.2, h7 13, dd 2.5.
       R1: 4+30+5+3+13+2.5+0.4 = 57.9 → blank 42.1 (high)
       Lift: bar1 33 → 60.9 → 39.1 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.33, "2bar": 0.050, "3bar": 0.030,
          "high7": 0.130, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.050, "3bar": 0.030,
          "high7": 0.105, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.050, "3bar": 0.025,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GGG_bar3_3", cand_ggg_bar3_lift))


def cand_hhh_final_e_dd_sym():
    """HHH: FINAL_E w/ dd 2.4/2.4/2.4 — symmetric dd for stable PWDF."""
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.075, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HHH_dd24_sym", cand_hhh_final_e_dd_sym))


def cand_iii_strong_g510():
    """III: maximize g510 via bar1 high but cherry low.
       cherry 3/2/1.5, bar1 33/29/24, bar2 4, bar3 1.2, h7 14/11/7, dd 2.4.
    """
    R1 = {"cherry": 0.030, "1bar": 0.33, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.24, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("III_strong_g510_low_cherry", cand_iii_strong_g510))


def cand_jjj_lower_rtp():
    """JJJ: aim for RTP ~95. Drop high7 to 13/10/7, lift cherry 4/3/2.2, FINAL_E rest, dd 2.4.
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.130, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJJ_h7_drop", cand_jjj_lower_rtp))


def cand_kkk_low_rtp_2():
    """KKK: dd 2.3 (cadence ~1/82k), h7 12/10/6.5, FINAL_E core.
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.065, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KKK_dd23_h7_12", cand_kkk_low_rtp_2))


# -----------------------------------------------------------------------
# Round 6 — bring R1 blank below 40, keep g510 > g15, RTP in band
# Best so far: JJJ (g510=14.16, g15=13.23, RTP 95.14, R1 blank 40.5)
# Strategy: lift R1 non-blank by 0.5-1pp without breaking other constraints
# -----------------------------------------------------------------------

def cand_lll_jjj_R1_lift():
    """LLL: JJJ with bar1 R1 35 + h7 R1 14 → R1 non-blank += 1.5pp.
       JJJ: 4+34+4.5+1.2+13+2.4+0.4 = 59.5 (R1 blank 40.5)
       LLL: 4+35+4.5+1.2+14+2.4+0.4 = 61.5 → R1 blank 38.5 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.35, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LLL_jjj_R1_lift", cand_lll_jjj_R1_lift))


def cand_mmm_jjj_cherry_R1_lift():
    """MMM: JJJ with cherry R1 5 → R1 non-blank += 1pp.
       Also lift R1 h7 by 1 → 5+34+4.5+1.2+14+2.4+0.4 = 61.5 → R1 blank 38.5
    """
    R1 = {"cherry": 0.050, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("MMM_jjj_cherry5", cand_mmm_jjj_cherry_R1_lift))


def cand_nnn_h7_lift_balance():
    """NNN: lift R1 h7 to 16 (from JJJ 13) and cherry 4.5, RTP balance.
       4.5+34+4.5+1.2+16+2.4+0.4 = 63 → R1 blank 37
       But that may inflate RTP.
    """
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.075, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("NNN_jjj_h7_16", cand_nnn_h7_lift_balance))


def cand_ooo_R1_dense_more_bar3():
    """OOO: bar3 1.5 R1 (more visible), bar2 5, bar1 34, cherry 4, h7 14.
       4+34+5+1.5+14+2.4+0.4 = 61.3 → R1 blank 38.7 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.105, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.075, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("OOO_bar3_1.5_bar2_5", cand_ooo_R1_dense_more_bar3))


def cand_ppp_h7_14_lift_R1():
    """PPP: bar1 33, cherry 5, h7 14 → 5+33+4.5+1.2+14+2.4+0.4 = 60.5 → R1 blank 39.5 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.105, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("PPP_bar1_33_cherry5", cand_ppp_h7_14_lift_R1))


def cand_qqq_balanced_pareto_relief():
    """QQQ: deliberate attempt to relieve pareto trap.
       Make cherry R1 6 (high cherry brand), bar1 30 (lower), bar2 6, bar3 2,
       h7 14 (moderate), dd 2.5.
       6+30+6+2+14+2.5+0.4 = 60.9 → R1 blank 39.1 ✓
    """
    R1 = {"cherry": 0.060, "1bar": 0.30, "2bar": 0.060, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.27, "2bar": 0.060, "3bar": 0.020,
          "high7": 0.110, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.22, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.075, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("QQQ_pareto_relief", cand_qqq_balanced_pareto_relief))


def cand_rrr_jjj_with_h7_15():
    """RRR: JJJ but h7 R1 14 instead of 13. 4+34+4.5+1.2+14+2.4+0.4 = 60.5 → blank 39.5 ✓
    """
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("RRR_jjj_h7_14", cand_rrr_jjj_with_h7_15))


def cand_sss_bar1_33_h7_14_cherry4():
    """SSS: tighter — bar1 33, cherry 4, h7 14, dd 2.4.
       4+33+4.5+1.2+14+2.4+0.4 = 59.5 → blank 40.5 (still over)
       Lift cherry 4.5 → 5+33+4.5+1.2+14+2.4+0.4 = 60.1 → blank 39.9
    """
    R1 = {"cherry": 0.045, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.105, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("SSS_bar1_33_cherry45", cand_sss_bar1_33_h7_14_cherry4))


def cand_ttt_strict_pareto_relief():
    """TTT: pareto relief variant — bar1 28, bar2 8, bar3 3 (all in [5%, 25%] range likely),
       cherry 4.5, h7 14, dd 2.5.
       4.5+28+8+3+14+2.5+0.4 = 60.4 → R1 blank 39.6 ✓
       But g510 might drop since bar1 lower. Test it.
    """
    R1 = {"cherry": 0.045, "1bar": 0.28, "2bar": 0.080, "3bar": 0.030,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.075, "3bar": 0.025,
          "high7": 0.105, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.21, "2bar": 0.070, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("TTT_pareto_relief_v2", cand_ttt_strict_pareto_relief))


def cand_uuu_dense_balanced():
    """UUU: cherry 5, bar1 28, bar2 7, bar3 2.5, h7 15, dd 2.5.
       5+28+7+2.5+15+2.5+0.4 = 60.4 → blank 39.6 ✓
       bar1 share ~30% (still over 25% but close).
    """
    R1 = {"cherry": 0.050, "1bar": 0.28, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.150, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.25, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.21, "2bar": 0.065, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("UUU_bar1_28_balanced", cand_uuu_dense_balanced))


def cand_vvv_more_h7_less_bar1():
    """VVV: cherry 4, bar1 25, bar2 7, bar3 2, h7 19, dd 2.5.
       4+25+7+2+19+2.5+0.4 = 59.9 → R1 blank 40.1 (over)
       Lift bar1 to 27: 4+27+7+2+19+2.5+0.4 = 61.9 → 38.1 ✓
       But h7 19 might push g2050+ over caps.
    """
    R1 = {"cherry": 0.040, "1bar": 0.27, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.190, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.24, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.20, "2bar": 0.065, "3bar": 0.018,
          "high7": 0.085, "doublediamond": 0.024, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("VVV_bar1_27_h7_19", cand_vvv_more_h7_less_bar1))


# -----------------------------------------------------------------------
# Round 7 — RTP between [94.5, 96] AND R1 blank ≤ 40 AND g510 > g15
# Best candidates: JJJ (95.14, 40.5 R1, g510=14.16>g15=13.23)
# Need: ↓RTP by 0.5pp without losing g510 lead AND lift R1 density by 0.5pp
# -----------------------------------------------------------------------

def cand_www_jjj_tweak1():
    """WWW: JJJ but cherry 4 R1 → 4.5 (+0.5 R1 density) and h7 13 → 12.5 (slight RTP drop).
       JJJ: 4+34+4.5+1.2+13+2.4+0.4 = 59.5 → blank 40.5
       WWW: 4.5+34+4.5+1.2+12.5+2.4+0.4 = 59.5 → blank 40.5 (same!)
       Need to lift R1 nonblank more. Try h7 14, cherry 4.5 → 4.5+34+4.5+1.2+14+2.4+0.4 = 61
       → blank 39 ✓. But RTP will go up.
    """
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.135, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.065, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("WWW_jjj_h7_13.5", cand_www_jjj_tweak1))


def cand_xxx_jjj_dd_lower():
    """XXX: JJJ but dd 2.3 (RTP drops, cadence 1/82k). And lift R1 cherry/h7 a touch.
       4.5+34+4.5+1.2+13.5+2.3+0.4 = 60.4 → blank 39.6 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.135, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.065, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("XXX_jjj_dd23", cand_xxx_jjj_dd_lower))


def cand_yyy_jjj_smaller_h7():
    """YYY: JJJ exact but h7 12/10/6.5 (lower than JJJ's 13/10/7).
       4+34+4.5+1.2+12+2.4+0.4 = 58.5 → blank 41.5 (worse R1)
       Skip and try diff approach.
       Lower bar1 33 to compensate for h7 drop. 4+33+4.5+1.2+13+2.4+0.4 = 58.5 → 41.5
       Bad. Try add cherry: 4.5+33+4.5+1.2+13+2.4+0.4 = 59 → 41
       Try add bar2: 4+33+5+1.2+13+2.4+0.4 = 59 → 41
       Hmm — need different angle.
    """
    R1 = {"cherry": 0.045, "1bar": 0.33, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.105, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.050, "3bar": 0.015,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("YYY_softer_bar1", cand_yyy_jjj_smaller_h7))


def cand_zzz_jjj_with_R1_cherry_h7_density():
    """ZZZ: JJJ + cherry R1 4.5 + h7 R1 14 (small lift) + dd 2.3 (offset).
       4.5+34+4.5+1.2+14+2.3+0.4 = 60.9 → blank 39.1 ✓
       Should be RTP ~ JJJ 95.14 + cherry_diff + h7_diff - dd_diff ~ 95
    """
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.140, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.100, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.065, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("ZZZ_R1_cherry45_h7_14_dd23", cand_zzz_jjj_with_R1_cherry_h7_density))


def cand_aaaa_low_blank_R1():
    """AAAA: target R1 blank ~ 35-38. cherry 5 (slightly higher) + bar1 33 + h7 16 + dd 2.4.
       5+33+4.5+1.2+16+2.4+0.4 = 62.5 → blank 37.5 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("AAAA_R1_blank_37.5", cand_aaaa_low_blank_R1))


def cand_bbbb_tighter_RTP():
    """BBBB: target RTP ~95. Drop dd to 2.2 (cadence ~1/94k), drop h7 to 12/10/6.
       4+34+4.5+1.2+12+2.2+0.4 = 58.3 → R1 blank 41.7 (over)
       Lift cherry 5 → 5+34+4.5+1.2+12+2.2+0.4 = 59.3 → 40.7 (still over)
       Lift bar1 35 → 5+35+4.5+1.2+12+2.2+0.4 = 60.3 → 39.7 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.35, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.120, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.095, "doublediamond": 0.022, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.060, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("BBBB_dd22_h7_12", cand_bbbb_tighter_RTP))


def cand_cccc_target_95():
    """CCCC: targeted at RTP 95, R1 blank 38, g510 > g15.
       cherry 4.5 / bar1 34 / bar2 5 / bar3 1.5 / h7 14 / dd 2.3 / jp 0.4
       4.5+34+5+1.5+14+2.3+0.4 = 61.7 → R1 blank 38.3 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.140, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.065, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("CCCC_target_95_blank_38", cand_cccc_target_95))


def cand_dddd_target_94_5():
    """DDDD: try for sub-95 RTP. dd 2.2 (cadence 1/94k), h7 12, cherry 4.5, bar1 34.
       4.5+34+5+1.5+12+2.2+0.4 = 59.6 → R1 blank 40.4 (over)
       Lift bar1 35 → 4.5+35+5+1.5+12+2.2+0.4 = 60.6 → R1 blank 39.4 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.35, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.120, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.095, "doublediamond": 0.022, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.060, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("DDDD_target_945", cand_dddd_target_94_5))


def cand_eeee_target_94_8():
    """EEEE: tune the dial more. cherry 4.5, bar1 34, bar2 5, bar3 1.5, h7 13, dd 2.25.
       Wild cadence 2.25^2 * 2.25 = 1.14e-5 → 1/87k (in band)
       4.5+34+5+1.5+13+2.25+0.4 = 60.65 → R1 blank 39.35
    """
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.130, "doublediamond": 0.0225, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.100, "doublediamond": 0.0225, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.05, "3bar": 0.015,
          "high7": 0.065, "doublediamond": 0.0225, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("EEEE_dd225_balanced", cand_eeee_target_94_8))


def cand_ffff_balance_family_share():
    """FFFF: target bar1 share ~ 30-35% (still over 25 cap but less than 41%).
       lower bar1 to 30/27/22. cherry 5, h7 14, bar2 6, bar3 2, dd 2.3.
       5+30+6+2+14+2.3+0.4 = 59.7 → R1 blank 40.3 (over)
       Lift bar1 to 31 → 60.7 → 39.3 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.31, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.140, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.27, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.105, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.22, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("FFFF_bar1_31_balanced", cand_ffff_balance_family_share))


def cand_gggg_pareto_relief_v3():
    """GGGG: aggressive pareto relief — bar1 25/22/19, bar2 9, bar3 3.5, cherry 5,
       h7 15, dd 2.4 (cadence 1/72k).
       5+25+9+3.5+15+2.4+0.4 = 60.3 → R1 blank 39.7 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.25, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.22, "2bar": 0.09, "3bar": 0.035,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.19, "2bar": 0.080, "3bar": 0.030,
          "high7": 0.075, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("GGGG_bar1_25_balanced", cand_gggg_pareto_relief_v3))


# -----------------------------------------------------------------------
# Round 8 — try candidates with bar1 share 30-40% (between feasibility-of-v6
# and ideal 25% family cap). Push g510 with slightly less bar1 dominance.
# -----------------------------------------------------------------------

def cand_hhhh_bar1_30_g510_lead():
    """HHHH: bar1 30/27/22, bar2 6, bar3 2, cherry 4, h7 14/11/7, dd 2.4.
       4+30+6+2+14+2.4+0.4 = 58.8 → R1 blank 41.2 (over)
       Lift cherry 5 → 5+30+6+2+14+2.4+0.4 = 59.8 → 40.2 (still over)
       Lift bar1 31 → 5+31+6+2+14+2.4+0.4 = 60.8 → 39.2 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.31, "2bar": 0.06, "3bar": 0.02,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.27, "2bar": 0.06, "3bar": 0.02,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.22, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("HHHH_bar1_31_bar2_6", cand_hhhh_bar1_30_g510_lead))


def cand_iiii_bar1_28_bar2_6_5():
    """IIII: bar1 28/25/21, bar2 6.5, bar3 2.5, cherry 5, h7 15/12/8, dd 2.4.
       5+28+6.5+2.5+15+2.4+0.4 = 59.8 → blank 40.2 (over)
       Lift bar1 30 → 5+30+6.5+2.5+15+2.4+0.4 = 61.4 → 38.6 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.30, "2bar": 0.065, "3bar": 0.025,
          "high7": 0.150, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.26, "2bar": 0.065, "3bar": 0.025,
          "high7": 0.115, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.21, "2bar": 0.060, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("IIII_bar1_30_bar2_65", cand_iiii_bar1_28_bar2_6_5))


def cand_jjjj_bar1_28_h7_lower():
    """JJJJ: bar1 28, bar2 6, bar3 2, cherry 4, h7 16/12/8, dd 2.4.
       4+28+6+2+16+2.4+0.4 = 58.8 → blank 41.2 (over)
       cherry 5: 5+28+6+2+16+2.4+0.4 = 59.8 → 40.2
       bar1 30: 5+30+6+2+16+2.4+0.4 = 61.4 → 38.6 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.30, "2bar": 0.06, "3bar": 0.02,
          "high7": 0.160, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.26, "2bar": 0.06, "3bar": 0.02,
          "high7": 0.120, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.21, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.075, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("JJJJ_bar1_30_h7_16", cand_jjjj_bar1_28_h7_lower))


def cand_kkkk_bar1_29_relief():
    """KKKK: bar1 29/26/22, bar2 5.5, bar3 1.8, cherry 4.5, h7 14/11/7, dd 2.4.
       4.5+29+5.5+1.8+14+2.4+0.4 = 57.6 → 42.4 (over)
       Lift bar1 32 → 4.5+32+5.5+1.8+14+2.4+0.4 = 60.6 → 39.4 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.32, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.23, "2bar": 0.050, "3bar": 0.018,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("KKKK_bar1_32_bar2_55", cand_kkkk_bar1_29_relief))


def cand_llll_lower_bar1_higher_h7_share():
    """LLLL: bar1 24/22/18, bar2 7, bar3 2.5, cherry 4.5, h7 18/15/10, dd 2.4.
       4.5+24+7+2.5+18+2.4+0.4 = 58.8 → 41.2 (over)
       Lift bar1 27 → 4.5+27+7+2.5+18+2.4+0.4 = 61.4 → 38.6 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.27, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.180, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.24, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.20, "2bar": 0.065, "3bar": 0.022,
          "high7": 0.085, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("LLLL_bar1_27_h7_18", cand_llll_lower_bar1_higher_h7_share))


def cand_mmmm_bar1_32_relief_v2():
    """MMMM: bar1 32/28/23, bar2 6, bar3 2, cherry 4.5, h7 14/11/7, dd 2.3 (lower RTP).
       4.5+32+6+2+14+2.3+0.4 = 61.2 → blank 38.8 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.32, "2bar": 0.06, "3bar": 0.02,
          "high7": 0.140, "doublediamond": 0.023, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.06, "3bar": 0.02,
          "high7": 0.110, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.23, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("MMMM_bar1_32_bar2_6_dd23", cand_mmmm_bar1_32_relief_v2))


def cand_nnnn_bar1_31_h7_lower_dd_25():
    """NNNN: bar1 31/28/23, bar2 5.5, bar3 1.8, cherry 5, h7 13/10/7, dd 2.5.
       5+31+5.5+1.8+13+2.5+0.4 = 59.2 → blank 40.8 (over)
       Lift h7 14 → 60.2 → 39.8 ✓
    """
    R1 = {"cherry": 0.050, "1bar": 0.31, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.140, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.28, "2bar": 0.055, "3bar": 0.018,
          "high7": 0.105, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.23, "2bar": 0.050, "3bar": 0.018,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("NNNN_bar1_31_dd25", cand_nnnn_bar1_31_h7_lower_dd_25))


def cand_oooo_bar1_30_bar3_2_5_relief():
    """OOOO: bar1 30/27/22, bar2 6, bar3 2.5, cherry 4.5, h7 14/11/7, dd 2.4.
       4.5+30+6+2.5+14+2.4+0.4 = 59.8 → 40.2 (over)
       Lift bar1 31 → 60.8 → 39.2 ✓
    """
    R1 = {"cherry": 0.045, "1bar": 0.31, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.140, "doublediamond": 0.024, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.27, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.110, "doublediamond": 0.024, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.22, "2bar": 0.055, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.023, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)
CANDIDATES.append(("OOOO_bar1_31_bar3_2.5", cand_oooo_bar1_30_bar3_2_5_relief))


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main():
    print("\n" + "="*80)
    print("M15 v13b DESIGN — candidate exploration")
    print("="*80)
    print(f"Total candidates: {len(CANDIDATES)}")
    passes = []
    near_passes = []
    for name, fn in CANDIDATES:
        margs = fn()
        r = evaluate(margs)
        ok, summary = report(name, r, verbose=True)
        if ok:
            passes.append((name, r, summary))
        elif summary["n_fail"] == 0 and summary["direction_ok"]:
            near_passes.append((name, r, summary))

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total candidates: {len(CANDIDATES)}")
    print(f"Full PASS (hardlines + v6 dir + family in [5,25] + cadence + rtp_safe): {len(passes)}")
    print(f"Hardline-only pass (no family/cadence/rtp_safe constraint): {len(near_passes)}")
    if passes:
        print("\n--- FULL PASS candidates ---")
        for name, r, summary in passes:
            print(f"  {name}: total_rtp={r['total_rtp']:.3f}  g15={r['session_bucket'].get('ge1_lt5',0):.2f}  "
                  f"g510={r['session_bucket'].get('ge5_lt10',0):.2f}  g1020={r['session_bucket'].get('ge10_lt20',0):.2f}  "
                  f"wild_cadence=1/{r['wild_cadence']:.0f}")
            print(f"    family: cherry1={r['family_shares']['cherry1']:.1f}, bar1={r['family_shares']['bar1']:.1f}, "
                  f"bar2={r['family_shares']['bar2']:.1f}, bar3={r['family_shares']['bar3']:.1f}, "
                  f"bar_mixed={r['family_shares']['bar_mixed']:.1f}, high7={r['family_shares']['high7']:.1f}")
    if near_passes:
        print("\n--- HARDLINE-only pass (with family/cadence/rtp_safe violations) ---")
        for name, r, summary in near_passes:
            print(f"  {name}: total_rtp={r['total_rtp']:.3f}  g15={r['session_bucket'].get('ge1_lt5',0):.2f}")
            if summary["family_violations"]:
                print(f"    family violations: {summary['family_violations']}")
            if not summary["cadence_ok"]:
                print(f"    wild cadence: 1/{r['wild_cadence']:.0f}")
            if not summary["rtp_safe"]:
                print(f"    rtp not safe: {r['total_rtp']:.3f}")
    return passes, near_passes


if __name__ == "__main__":
    main()
