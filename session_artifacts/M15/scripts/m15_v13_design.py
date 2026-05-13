"""M15 v13 mode 1 — Designer candidate generator under v5 hardlines.

Reads USER_HARDLINES.md v5 (widened):
  - ge1_lt5 ∈ [10, 15]pp  (was [10, 12])
  - sum_1_20 ∈ [28, 36]pp  (was [28, 32])
  - bell-shape direction (qualitative): g15 < g510 + g1020, peak in 5-15× range

All 14 hardlines:
  H1  hit_session ∈ [15, 18]%
  H2  total_rtp ∈ [94, 96]%
  H3  R1 blank ∈ [30, 40]%
  H4  ge1_lt5 ∈ [10, 15]pp        ← v5 widened
  H5  sum_1_20 ∈ [28, 36]pp       ← v5 widened
  H6  ge20_lt50 ∈ [22, 32]pp
  H7  ge50_lt100 ∈ [17, 27]pp
  H8  ge100_lt200 ∈ [4, 14]pp
  H9  ge200_lt500 ∈ [0, 7.3]pp
  H10 R1 jp marginal ≤ 0.6%
  H11 R2 jp marginal ≤ 0.6%
  H12 R3 jp marginal ≤ 0.6%
  H13 paytable byte-equal (assumed; we don't touch spec)
  H14 feature_params byte-equal v9 (assumed; we lock & reuse v9)

Bell-shape direction: g15 < (g510 + g1020), peak bucket ∈ {ge5_lt10, ge10_lt20}.

Strategy (from main session hints):
  - cherry low (~2-3% per reel) → cherry-1 P ~7-9% → g15 cherry contribution ~7-9pp
  - bars asymmetric: R1 1bar 25-35%, R2/R3 1bar 22-28% to maximize bar1_pure (g510)
  - 2bar, 3bar present on every reel (≥ 2%) for visibility
  - high7 ~7-12% per reel
  - dd ~2-3% per reel
  - jp ≤ 0.5% per reel
  - td R3 ≈ 0.011 (matches v9 feature trigger rate, locked)

Output: candidate set table + best-fit marginals + per-pay-id RTP breakdown.
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

# bucket edges high→low, matches analytic_rtp._BUCKETS
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


def normalize(d: dict[str, float]) -> dict[str, float]:
    s = sum(d.values())
    return {k: v / s for k, v in d.items() if v > 0}


def make_marginals(R1: dict, R2: dict, R3: dict) -> list[dict[str, float]]:
    """Add blank residual and normalize."""
    out = []
    for R in (R1, R2, R3):
        R = dict(R)
        non_blank = sum(R.values())
        R["blank"] = max(0.001, 1.0 - non_blank)
        out.append(normalize(R))
    return out


def evaluate(margs: list[dict[str, float]]) -> dict:
    """Run analytic_profile_from_marginals + add feature (session-centric)."""
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

    pay_rtp_session = {k: v * 100 for k, v in prof["pay_rtp"].items()}

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
        "pay_rtp_base": pay_rtp_session,
        "pay_hits": prof["pay_hits"],
        "margs": margs,
    }


def check14(r: dict) -> list[tuple[str, float, str]]:
    """Return list of (name, value, status) for all 14 hardlines.
    status ∈ {'PASS', 'FAIL'}.
    """
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


def check_bell(r: dict) -> tuple[bool, str]:
    s = r["session_bucket"]
    g15 = s.get("ge1_lt5", 0)
    g510 = s.get("ge5_lt10", 0)
    g1020 = s.get("ge10_lt20", 0)
    # Direction: g15 < (g510 + g1020). Peak bucket should be g510 or g1020.
    bell_pass = g15 < (g510 + g1020)
    # Peak: largest of {g15, g510, g1020} should be g510 or g1020 (not g15)
    peak_g15 = g15 >= g510 and g15 >= g1020
    peak_g510 = g510 >= g15 and g510 >= g1020
    peak_g1020 = g1020 >= g15 and g1020 >= g510
    if peak_g15:
        peak = "ge1_lt5 (BAD — bell-shape violated)"
        bell_pass = False
    elif peak_g510:
        peak = "ge5_lt10"
    elif peak_g1020:
        peak = "ge10_lt20"
    else:
        peak = "?"
    return bell_pass, peak


def report(name: str, r: dict, verbose: bool = True) -> tuple[bool, dict]:
    """Return (all_pass, summary)."""
    checks = check14(r)
    bell_ok, peak = check_bell(r)
    n_fail = sum(1 for _, _, st, _ in checks if st == "FAIL")
    if verbose:
        print(f"\n======== Candidate: {name} ========")
        print(f"  total_rtp={r['total_rtp']:.3f}pp  hit_session={r['hit_session']:.3f}%")
        print(f"  base_rtp={r['base_rtp']:.3f}pp  feature_rtp={r['feature_rtp']:.3f}pp  "
              f"(split {r['base_rtp']/r['total_rtp']*100:.0f}:{r['feature_rtp']/r['total_rtp']*100:.0f})")
        print(f"  R1_blank={r['r1_blank']:.3f}%  R2_blank={r['r2_blank']:.3f}%  R3_blank={r['r3_blank']:.3f}%")
        print(f"  trigger={r['trigger']:.3f}%")
        s = r["session_bucket"]
        g15 = s.get("ge1_lt5", 0)
        g510 = s.get("ge5_lt10", 0)
        g1020 = s.get("ge10_lt20", 0)
        print(f"  Buckets: g15={g15:.3f}  g510={g510:.3f}  g1020={g1020:.3f}  "
              f"g2050={s.get('ge20_lt50',0):.3f}  g50100={s.get('ge50_lt100',0):.3f}  "
              f"g100200={s.get('ge100_lt200',0):.3f}  g200500={s.get('ge200_lt500',0):.3f}")
        print(f"  Bell-shape: peak={peak}  g15<(g510+g1020)? g15={g15:.2f} vs g510+g1020={g510+g1020:.2f}")
        # Pay-id breakdown
        ph = r.get("pay_hits", {})
        ev = {
            "1": "wild3 200x",
            "2": "h7+wild 30x",
            "3": "3bar 20x",
            "4": "cherry3 15x",
            "5": "2bar 10x",
            "7": "1bar 5x",
            "8": "bar_mixed 2x",
            "9": "cherry1 1x",
            "21": "h7_pure 30x",
            "71": "cherry2 5x",
            "666": "topdollar",
        }
        if ph:
            print(f"  Pay_hits (1 in N):")
            for pid in ("9", "71", "4", "1", "2", "3", "5", "7", "8", "21"):
                p = ph.get(pid, 0)
                if p > 0:
                    print(f"    pay_id {pid:>3s} {ev.get(pid, ''):18s} hit={p*100:7.4f}%   1 in {1/p:>8.0f}")
        print(f"  Hardlines: {n_fail}/14 fail")
        for nm, val, st, (lo, hi) in checks:
            if st == "FAIL":
                print(f"    {st}  {nm:18s} = {val:8.3f}  target [{lo}, {hi}]")
    return (n_fail == 0 and bell_ok), {
        "checks": checks,
        "bell_ok": bell_ok,
        "peak": peak,
        "n_fail": n_fail,
        "r": r,
    }


# -----------------------------------------------------------------------
# CANDIDATES
# -----------------------------------------------------------------------
# Strategy hints from main session:
#   cherry ~2-3% per reel  → cherry-1 P ~7-9% → g15 contribution ~7-9pp
#   bars asymmetric: R1 1bar 25-35%, R2/R3 1bar 22-28%
#   2bar, 3bar present every reel ≥ 2%
#   high7 ~7-12% per reel
#   dd ~2-3% per reel
#   jp ≤ 0.5% per reel
#   td R3 ≈ 0.011

# Reasoning baseline:
# A: cherry 2.5% uniform; 1bar dominant; 2bar/3bar small; h7 8%; dd 2.5%
# B: cherry lower (2%); 1bar even more dominant; push bar1_pure to maximize g510
# C: like B but also push 2bar (g1020 peak)
# D: lower bars / more high7 (push higher-mult hits)
# E: very low cherry (1.5%) + balance bars
# F-J: parameter sweeps around best

CANDIDATES: list[tuple[str, callable]] = []


def cand_a():
    """Baseline R1 non-blank ~65% (R1 blank ~35%).
    cherry 2.5%, R1 1bar=23%, 2bar=14%, 3bar=4%, h7=10%, dd=4%."""
    R1 = {"cherry": 0.025, "1bar": 0.23, "2bar": 0.14, "3bar": 0.04,
          "high7": 0.10, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.21, "2bar": 0.14, "3bar": 0.04,
          "high7": 0.090, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.19, "2bar": 0.14, "3bar": 0.04,
          "high7": 0.060, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("A_baseline", cand_a))


def cand_b():
    """1bar-heavy + tight 3bar (limit bar_mixed)."""
    R1 = {"cherry": 0.02, "1bar": 0.27, "2bar": 0.12, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.24, "2bar": 0.12, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.21, "2bar": 0.12, "3bar": 0.025,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("B_1bar_heavy", cand_b))


def cand_c():
    """2bar-heavy — push g1020 to peak via bar2_pure (10×)."""
    R1 = {"cherry": 0.022, "1bar": 0.21, "2bar": 0.16, "3bar": 0.04,
          "high7": 0.09, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.19, "2bar": 0.16, "3bar": 0.04,
          "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.17, "2bar": 0.16, "3bar": 0.04,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("C_2bar_heavy", cand_c))


def cand_d():
    """Both 1bar and 2bar moderate, 3bar very low. Cherry low."""
    R1 = {"cherry": 0.02, "1bar": 0.24, "2bar": 0.14, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.22, "2bar": 0.14, "3bar": 0.025,
          "high7": 0.080, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.20, "2bar": 0.14, "3bar": 0.025,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("D_1bar+2bar", cand_d))


def cand_e():
    """Cherry ultra-low (1.2%) — focus cherry-1 minimal."""
    R1 = {"cherry": 0.012, "1bar": 0.25, "2bar": 0.14, "3bar": 0.030,
          "high7": 0.09, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.012, "1bar": 0.22, "2bar": 0.14, "3bar": 0.030,
          "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.012, "1bar": 0.20, "2bar": 0.14, "3bar": 0.030,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("E_low_cherry", cand_e))


def cand_f():
    """Balanced: cherry 2%, 1bar 23, 2bar 13, 3bar 0.03, h7 8.5%."""
    R1 = {"cherry": 0.02, "1bar": 0.23, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.21, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.080, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.19, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("F_balanced", cand_f))


def cand_g():
    """1bar very heavy R1=30, low h7 — push g510 dominant."""
    R1 = {"cherry": 0.02, "1bar": 0.30, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.06, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.27, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.06, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.23, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.045, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("G_g510_dominant", cand_g))


def cand_h():
    """Asymmetric cherry R1=3, R2=2, R3=1 — R3 cherry minimum to break overlap."""
    R1 = {"cherry": 0.03, "1bar": 0.22, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.20, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.080, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.010, "1bar": 0.19, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("H_asym_cherry", cand_h))


def cand_i():
    """Low h7 (5%), high bars — bell shape via bar1_pure + bar2_pure."""
    R1 = {"cherry": 0.02, "1bar": 0.26, "2bar": 0.14, "3bar": 0.030,
          "high7": 0.05, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.23, "2bar": 0.14, "3bar": 0.030,
          "high7": 0.05, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.20, "2bar": 0.14, "3bar": 0.030,
          "high7": 0.04, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("I_low_h7_high_bar", cand_i))


def cand_j():
    """Tight balanced: cherry 1.8%, 1bar 24%, 2bar 13%, 3bar 0.03, h7 7.5%, dd 3%."""
    R1 = {"cherry": 0.018, "1bar": 0.24, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.018, "1bar": 0.22, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.070, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.20, "2bar": 0.13, "3bar": 0.030,
          "high7": 0.050, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("J_tight", cand_j))


def cand_k():
    """KEY INSIGHT: 1bar VERY HIGH, 2bar and 3bar LOW (kills bar_mixed).
    1bar+wild substitution gives g1020 boost (5× × 2 wilds = 10×).
    Cherry 1.5% to keep cherry-1 low."""
    R1 = {"cherry": 0.015, "1bar": 0.30, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.10, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.27, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.095, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.24, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.060, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("K_1bar_high_minor_others", cand_k))


def cand_l():
    """K variant — even more 1bar, less h7."""
    R1 = {"cherry": 0.015, "1bar": 0.32, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.29, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.080, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.25, "2bar": 0.05, "3bar": 0.02,
          "high7": 0.060, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("L_1bar_max", cand_l))


def cand_m():
    """K variant — 1bar high + boost dd (more wild = more 5×→10×→20× chains)."""
    R1 = {"cherry": 0.015, "1bar": 0.28, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.08, "doublediamond": 0.055, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.25, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.075, "doublediamond": 0.060, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.22, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.055, "doublediamond": 0.035, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("M_1bar_high+wild_boost", cand_m))


def cand_n():
    """N: balance bars but 3bar very low to limit bar_mixed."""
    R1 = {"cherry": 0.02, "1bar": 0.25, "2bar": 0.08, "3bar": 0.015,
          "high7": 0.09, "doublediamond": 0.04, "jackpot": 0.004}
    R2 = {"cherry": 0.02, "1bar": 0.23, "2bar": 0.08, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.20, "2bar": 0.08, "3bar": 0.015,
          "high7": 0.060, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("N_3bar_min", cand_n))


def cand_o():
    """K-like but with all 3bar = 0 (NOT allowed by visibility, but as floor study)."""
    R1 = {"cherry": 0.015, "1bar": 0.30, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.105, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.015, "1bar": 0.27, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.100, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.015, "1bar": 0.24, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.065, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("O_high_h7_1bar", cand_o))


def cand_p():
    """K-pattern + more cherry (2.2%) + boost R1 1bar to 35% — push hit and bell-shape."""
    R1 = {"cherry": 0.022, "1bar": 0.35, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.11, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.31, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.10, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.27, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.07, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("P_cherry+1bar_max", cand_p))


def cand_q():
    """Push 1bar to 40%/35%/30% — extreme g510 (3×1bar at 5×) push."""
    R1 = {"cherry": 0.020, "1bar": 0.40, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.09, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.35, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("Q_1bar_extreme", cand_q))


def cand_r():
    """Moderate 1bar/h7 + add wild for cascading multiplier — balance hit."""
    R1 = {"cherry": 0.025, "1bar": 0.33, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.29, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.060, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("R_balanced_1bar_high", cand_r))


def cand_s():
    """1bar high + medium cherry + balanced h7 + slight 2bar."""
    R1 = {"cherry": 0.020, "1bar": 0.31, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.095, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.28, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.090, "doublediamond": 0.045, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.030, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("S_balanced", cand_s))


def cand_t():
    """Tighter: P-like, push h7 less, more dd."""
    R1 = {"cherry": 0.020, "1bar": 0.33, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.050, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.055, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.040, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("T_dd_boost", cand_t))


def cand_u():
    """Q dial-down: 1bar R1=33/30/26 instead of 40/35/30, cherry 0.020 — pull rtp toward 95."""
    R1 = {"cherry": 0.020, "1bar": 0.33, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.045, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("U_Q_dialed_down", cand_u))


def cand_v():
    """Q variant — 1bar even lower (30/27/24)."""
    R1 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.27, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.24, "2bar": 0.04, "3bar": 0.020,
          "high7": 0.050, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("V_1bar_low", cand_v))


def cand_w():
    """Q variant — even lower 1bar + slight h7 boost + slight cherry boost."""
    R1 = {"cherry": 0.025, "1bar": 0.28, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.090, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.25, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.22, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("W_balanced_v2", cand_w))


def cand_x():
    """Lower wild — see effect on h7+wild high-bucket overflow."""
    R1 = {"cherry": 0.022, "1bar": 0.30, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.27, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("X_low_wild", cand_x))


def cand_y():
    """1bar moderate + lower h7, lower wild."""
    R1 = {"cherry": 0.022, "1bar": 0.30, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.065, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.27, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.060, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.045, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("Y_low_h7_low_wild", cand_y))


def cand_z():
    """Y variant — slight more h7 / dd, tune to ~95% total."""
    R1 = {"cherry": 0.022, "1bar": 0.30, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.072, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.27, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.068, "doublediamond": 0.029, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.050, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("Z_tuned", cand_z))


def cand_aa():
    """Target: 1bar=0.30/0.28/0.26 (gives bar1_pure×5 ≈ 11pp g510),
    cherry 0.020, dd 0.025 (lower wild), h7 0.075. Targets base_rtp ~44pp."""
    R1 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.28, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.029, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.050, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("AA_tuned_1bar30", cand_aa))


def cand_bb():
    """1bar 0.32/0.29/0.26 (higher) + dd 0.022 (lower wild)."""
    R1 = {"cherry": 0.020, "1bar": 0.32, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.29, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.050, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BB_higher_1bar_low_dd", cand_bb))


def cand_cc():
    """Bigger 1bar diff: 0.34/0.30/0.26 — push R1 winners-friendly."""
    R1 = {"cherry": 0.020, "1bar": 0.34, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.070, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.050, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("CC_R1winnerR3miser", cand_cc))


def cand_dd():
    """Aim sum_1_20 ~32pp + total ~95. Lower 1bar further (0.28/0.26/0.24)."""
    R1 = {"cherry": 0.022, "1bar": 0.28, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.24, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("DD_lower_1bar", cand_dd))


def cand_ee():
    """1bar 0.30/0.27/0.24 + dd 0.025 — middle-ground tuned."""
    R1 = {"cherry": 0.022, "1bar": 0.30, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.27, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.24, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("EE_middle_ground", cand_ee))


def cand_ff():
    """Add density: cherry 2.5%, 1bar 30/27/24, 2bar 8, h7 9, dd 3 — push base toward 44pp."""
    R1 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.090, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.27, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FF_density_push", cand_ff))


def cand_gg():
    """Slightly more 2bar = more g1020 — keeping bell-shape."""
    R1 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.09, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.27, "2bar": 0.09, "3bar": 0.025,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.09, "3bar": 0.025,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("GG_more_2bar", cand_gg))


def cand_hh():
    """Light density add over FF — h7 +10, dd similar."""
    R1 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.10, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.27, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.07, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("HH_h7_boost", cand_hh))


def cand_ii():
    """Push everything moderately. cherry 2.5%, 1bar 32/29/25, 2bar 7, h7 9.5."""
    R1 = {"cherry": 0.025, "1bar": 0.32, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.095, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.29, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.090, "doublediamond": 0.033, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.065, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("II_balanced_push", cand_ii))


def cand_jj():
    """Even bigger 1bar (35/30/25) + h7 8 + dd 2.5."""
    R1 = {"cherry": 0.025, "1bar": 0.35, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.080, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.080, "doublediamond": 0.029, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.06, "3bar": 0.025,
          "high7": 0.058, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("JJ_big_R1_1bar", cand_jj))


def cand_kk():
    """Higher density: 1bar 32/28/24, 2bar 8, h7 8.5, dd 3, cherry 2.5."""
    R1 = {"cherry": 0.025, "1bar": 0.32, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.28, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.055, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("KK_target_aim", cand_kk))


def cand_ll():
    """1bar 36/32/26 push g510 above g15. Cherry 2.2% to keep g15 down."""
    R1 = {"cherry": 0.022, "1bar": 0.36, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.08, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.32, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.058, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("LL_36_32_26", cand_ll))


def cand_mm():
    """LL variant — cherry even lower (1.8%) — push g510 peak."""
    R1 = {"cherry": 0.018, "1bar": 0.36, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.08, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.018, "1bar": 0.32, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.058, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("MM_lower_cherry_36", cand_mm))


def cand_nn():
    """1bar 38/33/28 — even bigger push, pure asymmetric R1 winners."""
    R1 = {"cherry": 0.020, "1bar": 0.38, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.07, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.33, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.07, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.28, "2bar": 0.05, "3bar": 0.020,
          "high7": 0.050, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("NN_38_33_28", cand_nn))


def cand_oo():
    """1bar 34/30/26 — middle between JJ (35/30/25) and LL (36/32/26)."""
    R1 = {"cherry": 0.020, "1bar": 0.34, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.018, "1bar": 0.26, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("OO_34_30_26", cand_oo))


def cand_pp():
    """LL + 2bar lift (push g1020 too)."""
    R1 = {"cherry": 0.022, "1bar": 0.36, "2bar": 0.08, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.32, "2bar": 0.08, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.08, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("PP_LL_more_2bar", cand_pp))


def cand_qq():
    """LL with finer tune — 1bar 36/31/27."""
    R1 = {"cherry": 0.022, "1bar": 0.36, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.08, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.31, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.27, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.058, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("QQ_LL_finetune", cand_qq))


def cand_rr():
    """1bar 32/29/25 (less product → less g510). cherry 2.2%, more h7 8.5+."""
    R1 = {"cherry": 0.022, "1bar": 0.32, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.29, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("RR_1bar32_29_25", cand_rr))


def cand_ss():
    """1bar 33/29/25 + larger 2bar (10%) for g1020 — pursue both g510 and g1020."""
    R1 = {"cherry": 0.020, "1bar": 0.33, "2bar": 0.10, "3bar": 0.020,
          "high7": 0.08, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.29, "2bar": 0.10, "3bar": 0.020,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.10, "3bar": 0.020,
          "high7": 0.055, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("SS_g510_g1020_dual", cand_ss))


def cand_tt():
    """1bar 30/27/24 + 2bar 10 + larger h7 9 — more h7+wild → g2050."""
    R1 = {"cherry": 0.022, "1bar": 0.30, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.27, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.24, "2bar": 0.10, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("TT_balanced_30_2bar10", cand_tt))


def cand_uu():
    """1bar 33/30/25 — close to QQ/LL but less g510. Adjust cherry for hit balance."""
    R1 = {"cherry": 0.022, "1bar": 0.33, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.022, "1bar": 0.30, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("UU_33_30_25", cand_uu))


def cand_vv():
    """UU + cherry 0.020 (lower) — make sure g15 cap at 13-14pp."""
    R1 = {"cherry": 0.020, "1bar": 0.33, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.020, "1bar": 0.30, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("VV_UU_lower_cherry", cand_vv))


def cand_ww():
    """RR + boost density: cherry 2.5%, h7 9.5 — more density to get R1 blank under 40."""
    R1 = {"cherry": 0.025, "1bar": 0.32, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.095, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.29, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.090, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.08, "3bar": 0.025,
          "high7": 0.065, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("WW_RR_more_density", cand_ww))


def cand_xx():
    """LL-base with more density: 1bar 36/32/26 → 34/30/25, add cherry +0.5%, h7 +1%, 2bar +1%."""
    R1 = {"cherry": 0.025, "1bar": 0.34, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.09, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.07, "3bar": 0.020,
          "high7": 0.060, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("XX_LL_more_cherry_h7", cand_xx))


def cand_yy():
    """1bar 33/30/25 + 2bar 7 + 3bar 0.03 + cherry 0.025 + h7 0.085 — careful balance."""
    R1 = {"cherry": 0.025, "1bar": 0.33, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.07, "3bar": 0.030,
          "high7": 0.058, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("YY_33_30_25_balanced", cand_yy))


def cand_zz():
    """XX + 3bar nudged up — push g2050 above 22pp floor."""
    R1 = {"cherry": 0.025, "1bar": 0.34, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.09, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.07, "3bar": 0.025,
          "high7": 0.060, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("ZZ_XX_3bar_up", cand_zz))


def cand_aaa():
    """LL with 1bar 34/30/25 + light density add."""
    R1 = {"cherry": 0.023, "1bar": 0.34, "2bar": 0.07, "3bar": 0.022,
          "high7": 0.085, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.023, "1bar": 0.30, "2bar": 0.07, "3bar": 0.022,
          "high7": 0.080, "doublediamond": 0.032, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.07, "3bar": 0.022,
          "high7": 0.058, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("AAA_LL_dense", cand_aaa))


def cand_bbb():
    """1bar 35/31/26 + cherry 2.3, h7 8.5, dd 3 — looking for sweet spot."""
    R1 = {"cherry": 0.023, "1bar": 0.35, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.085, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.023, "1bar": 0.31, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.058, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BBB_35_31_26_balanced", cand_bbb))


def cand_ccc():
    """Try maxing out density on R1: more cherry + more h7 + slight more dd."""
    R1 = {"cherry": 0.030, "1bar": 0.34, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.10, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.023, "1bar": 0.30, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.085, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.058, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("CCC_dense_R1", cand_ccc))


def cand_ddd():
    """BBB but with LOW dd (0.015-0.018) — wild much less impactful, drop RTP."""
    R1 = {"cherry": 0.025, "1bar": 0.35, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.085, "doublediamond": 0.018, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.31, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.080, "doublediamond": 0.020, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.058, "doublediamond": 0.015, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("DDD_BBB_low_dd", cand_ddd))


def cand_eee():
    """1bar 34/30/25 + h7 9 + dd 0.020 — keep density up but balance value."""
    R1 = {"cherry": 0.025, "1bar": 0.34, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.09, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.085, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.06, "3bar": 0.022,
          "high7": 0.06, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("EEE_1bar34_low_dd", cand_eee))


def cand_fff():
    """BBB with super low dd 0.015 + a bit more cherry."""
    R1 = {"cherry": 0.030, "1bar": 0.35, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.090, "doublediamond": 0.015, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.31, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.018, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.060, "doublediamond": 0.012, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FFF_max_cherry_min_dd", cand_fff))


def cand_ggg():
    """BBB with even lower dd 0.012 — push hard."""
    R1 = {"cherry": 0.027, "1bar": 0.35, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.090, "doublediamond": 0.012, "jackpot": 0.004}
    R2 = {"cherry": 0.027, "1bar": 0.31, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.015, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.06, "3bar": 0.020,
          "high7": 0.060, "doublediamond": 0.010, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("GGG_BBB_ultra_low_dd", cand_ggg))


def cand_hhh():
    """KEY: 3bar ABSOLUTE MIN (0.010), 2bar low (0.04), but BIG h7 (0.13) to add density.
    This makes bar_mixed very small while h7 carries the 'big win' density."""
    R1 = {"cherry": 0.028, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.13, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.028, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("HHH_h7_carry", cand_hhh))


def cand_iii():
    """1bar 33/29/25 + low everything else. Tune cherry to fill density."""
    R1 = {"cherry": 0.035, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.11, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.025, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("III_more_cherry_balance", cand_iii))


def cand_jjj():
    """HHH variant — dd lower (0.020)."""
    R1 = {"cherry": 0.030, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.13, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("JJJ_HHH_low_dd", cand_jjj))


def cand_kkk():
    """1bar 30/27/23 + h7 12 + low 2bar/3bar. Push h7-mediated bell-shape."""
    R1 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.27, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.115, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.23, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.075, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("KKK_h7_12pct", cand_kkk))


def cand_lll():
    """HHH + boost cherry (0.035/0.035/0.030) — add hit + cherry-1 g15."""
    R1 = {"cherry": 0.035, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.13, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("LLL_HHH_more_cherry", cand_lll))


def cand_mmm():
    """HHH + cherry boost + dd slight reduce to keep total ≤ 96."""
    R1 = {"cherry": 0.035, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.13, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("MMM_HHH_cherry+lowdd", cand_mmm))


def cand_nnn():
    """III with reduced cherry (0.030/0.025/0.020) to bring total down."""
    R1 = {"cherry": 0.030, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.11, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.07, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("NNN_III_lower_cherry", cand_nnn))


def cand_ooo():
    """III with dd low (0.020) and cherry high (0.035/0.030/0.022)."""
    R1 = {"cherry": 0.035, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.11, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.07, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("OOO_III_low_dd_high_cherry", cand_ooo))


def cand_ppp():
    """Adapted: cherry 0.035/0.030/0.025 + 1bar 31/28/24 + 2bar 0.04 + h7 0.11 + dd 0.022.
    Goal: hit 15+, total ≤ 96, R1 blank ≤ 40."""
    R1 = {"cherry": 0.035, "1bar": 0.31, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.11, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.24, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.07, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("PPP_targeted_balance", cand_ppp))


def cand_qqq():
    """III variant — slightly drop 1bar to 32/28/23 to reduce total."""
    R1 = {"cherry": 0.035, "1bar": 0.32, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.23, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.07, "doublediamond": 0.022, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("QQQ_III_lower_1bar", cand_qqq))


def cand_rrr():
    """MMM + boost R1 density: cherry 0.04, h7 0.14 — fill R1 blank."""
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.14, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("RRR_MMM_more_dense_R1", cand_rrr))


def cand_sss():
    """MMM + cherry boost 0.040 across all reels — direct R1 fill + cherry-1 hit."""
    R1 = {"cherry": 0.040, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.13, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("SSS_MMM_cherry04", cand_sss))


def cand_ttt():
    """MMM + h7 0.15 R1 + 0.13 R2 + 0.09 R3 — fill via high7."""
    R1 = {"cherry": 0.035, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.13, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.09, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("TTT_MMM_h7_max", cand_ttt))


def cand_uuu():
    """MMM with bigger h7/cherry boost — full push to lower R1 blank."""
    R1 = {"cherry": 0.040, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.14, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("UUU_full_push", cand_uuu))


def cand_vvv():
    """MMM-base + push EVERYTHING on R1, R2 lighter, R3 sparse."""
    R1 = {"cherry": 0.045, "1bar": 0.33, "2bar": 0.050, "3bar": 0.012,
          "high7": 0.14, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("VVV_R1_heaviest", cand_vvv))


def cand_www():
    """VVV with more R1 density — push R1 blank lower."""
    R1 = {"cherry": 0.045, "1bar": 0.33, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("WWW_VVV_more_R1", cand_www))


def cand_xxx():
    """VVV-style with slightly more cherry + lower h7 to keep RTP."""
    R1 = {"cherry": 0.050, "1bar": 0.33, "2bar": 0.050, "3bar": 0.012,
          "high7": 0.14, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("XXX_VVV_more_cherry", cand_xxx))


def cand_yyy():
    """VVV-style with R1 cherry up + R1 1bar slight down."""
    R1 = {"cherry": 0.050, "1bar": 0.32, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.14, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("YYY_VVV_tuned_R1", cand_yyy))


def cand_zzz():
    """VVV-style with R1 cherry up + 2bar up — direct R1 density push."""
    R1 = {"cherry": 0.060, "1bar": 0.32, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.13, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("ZZZ_VVV_cherry06", cand_zzz))


def cand_robust_a():
    """WWW + boost middle R3 density: align with R1>R2>R3 winners-friendly direction.
    R3 still trigger reel so blank can be slightly high but not 56%."""
    R1 = {"cherry": 0.045, "1bar": 0.33, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.29, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.13, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.25, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.09, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("ROBUST_A", cand_robust_a))


def cand_robust_b():
    """Robust_A with mid-level cherry."""
    R1 = {"cherry": 0.040, "1bar": 0.33, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.13, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.25, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.09, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("ROBUST_B", cand_robust_b))


def cand_robust_c():
    """Robust_A + h7 slight reduce on R2 to bring total under 96."""
    R1 = {"cherry": 0.045, "1bar": 0.32, "2bar": 0.055, "3bar": 0.015,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.015,
          "high7": 0.085, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("ROBUST_C", cand_robust_c))


def cand_robust_d():
    """ROBUST_C with 1bar 31/28/24 — less 1bar to bring sum_1_20 down."""
    R1 = {"cherry": 0.045, "1bar": 0.31, "2bar": 0.060, "3bar": 0.020,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.28, "2bar": 0.050, "3bar": 0.020,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.24, "2bar": 0.050, "3bar": 0.020,
          "high7": 0.085, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("ROBUST_D", cand_robust_d))


def cand_bell_strong_a():
    """Stronger bell: 1bar 35/30/26 (higher), 2bar+3bar min (4/4/4 and 1.2/1.2/1.2),
    cherry 3.5/2.5/2.0 (lower R1 cherry for less cherry-1 g15)."""
    R1 = {"cherry": 0.035, "1bar": 0.35, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BELL_STRONG_A", cand_bell_strong_a))


def cand_bell_strong_b():
    """BELL_STRONG_A + cherry 3.0/2.5/2.0 to bring g15 lower."""
    R1 = {"cherry": 0.030, "1bar": 0.35, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BELL_STRONG_B", cand_bell_strong_b))


def cand_bell_strong_c():
    """1bar 33/30/26 + cherry 0.030 + h7 0.14 — slight bell weighting."""
    R1 = {"cherry": 0.030, "1bar": 0.33, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.14, "doublediamond": 0.025, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.30, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.26, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.020, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BELL_STRONG_C", cand_bell_strong_c))


def cand_bell_strong_d():
    """1bar 38/33/28 + cherry 3% + low h7 (so g100+ not blow up)."""
    R1 = {"cherry": 0.030, "1bar": 0.38, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.33, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.09, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.28, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.060, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BELL_STRONG_D", cand_bell_strong_d))


def cand_bell_strong_e():
    """BELL_STRONG_D + slight more cherry to push hit toward 15.5%."""
    R1 = {"cherry": 0.035, "1bar": 0.38, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.018, "jackpot": 0.004}
    R2 = {"cherry": 0.028, "1bar": 0.33, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.09, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.28, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.060, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BELL_STRONG_E", cand_bell_strong_e))


def cand_bell_strong_f():
    """Tighter: 1bar 36/32/28 + cherry 0.030 + h7 0.10 + dd 0.020."""
    R1 = {"cherry": 0.030, "1bar": 0.36, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.10, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.025, "1bar": 0.32, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.09, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.28, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.06, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("BELL_STRONG_F", cand_bell_strong_f))


def cand_final_a():
    """WWW with smaller 2bar/3bar to reduce bar_mixed and give g15 more headroom."""
    R1 = {"cherry": 0.045, "1bar": 0.34, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.26, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FINAL_A", cand_final_a))


def cand_final_b():
    """FINAL_A — slightly different. Cherry 0.040/0.030/0.022."""
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.022, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.26, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FINAL_B", cand_final_b))


def cand_final_c():
    """FINAL_A — slightly different. cherry 0.040/0.030/0.022, 1bar tweaked."""
    R1 = {"cherry": 0.040, "1bar": 0.35, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.028, "1bar": 0.30, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.26, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FINAL_C", cand_final_c))


def cand_final_d():
    """1bar 33/29/25 + cherry 0.035/0.028/0.022 + h7 0.15/0.12/0.08."""
    R1 = {"cherry": 0.035, "1bar": 0.33, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.028, "1bar": 0.29, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.025, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.040, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FINAL_D", cand_final_d))


def cand_final_e():
    """1bar 34/30/25 + cherry 0.040/0.030/0.022 + dd lower (0.018/0.020/0.015)."""
    R1 = {"cherry": 0.040, "1bar": 0.34, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.018, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.30, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.022, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.016, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FINAL_E", cand_final_e))


def cand_final_f():
    """Robust pick: 1bar 33/29/25 + cherry 0.040/0.030/0.022 — stronger bell + safer total."""
    R1 = {"cherry": 0.040, "1bar": 0.33, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.15, "doublediamond": 0.020, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.29, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.12, "doublediamond": 0.023, "jackpot": 0.004}
    R3 = {"cherry": 0.022, "1bar": 0.25, "2bar": 0.045, "3bar": 0.012,
          "high7": 0.08, "doublediamond": 0.018, "topdollar": 0.011, "jackpot": 0.003}
    return make_marginals(R1, R2, R3)


CANDIDATES.append(("FINAL_F", cand_final_f))


# -----------------------------------------------------------------------
# Run all + print
# -----------------------------------------------------------------------

def run_all(verbose: bool = True):
    results = []
    pass_list = []
    print("=== M15 v13 Designer — running candidates ===")
    print(f"Feature EV per trigger: {FEAT_EV_TOTAL:.4f}x")
    print(f"  Feature ge1_lt5 contribution (per trigger): {FEAT_BUCKET_EV.get('ge1_lt5', 0):.4f}x")
    for name, fn in CANDIDATES:
        margs = fn()
        r = evaluate(margs)
        all_pass, summary = report(name, r, verbose=verbose)
        results.append((name, all_pass, summary))
        if all_pass:
            pass_list.append((name, summary))
    print(f"\n=== Summary: {len(pass_list)}/{len(results)} candidates PASS all 14 + bell-shape ===")
    for nm, summ in pass_list:
        s = summ["r"]["session_bucket"]
        g15 = s.get("ge1_lt5", 0)
        sum120 = g15 + s.get("ge5_lt10", 0) + s.get("ge10_lt20", 0)
        print(f"  PASS {nm}: g15={g15:.3f}  sum120={sum120:.3f}  total={summ['r']['total_rtp']:.3f}  "
              f"hit={summ['r']['hit_session']:.3f}  peak={summ['peak']}")
    return results, pass_list


if __name__ == "__main__":
    results, passes = run_all(verbose=True)
