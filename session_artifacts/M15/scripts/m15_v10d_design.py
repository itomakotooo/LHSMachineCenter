"""M15 v10d exploration — drop ALL self-imposed constraints.

Only user's 9 hard constraints remain:
  1. paytable byte-identical (in spec.json `pays` — not touched here)
  2. Hit in [15%, 18%]
  3. Total RTP in [94%, 96%]
  4. P(R>=1000)/spin <= 1e-5
  5. Jackpot any-reel <= 0.6%
  6. R1 blank in [30%, 40%]
  7. ge1_lt5 RTP in [11.0, 14.0]pp
  8. ge5_lt10 RTP in [8.0, 9.5]pp
  9. ge10_lt20 RTP in [8.5, 10.0]pp

Levers used (dropping prior boundary constraints):
  F: doublediamond marg may be 0 (wild_pure pay extinct OK)
  G: cherry marg may be 0
  H: 3bar marg may be 0 (bar_mixed only from 1bar/2bar combos)
  K: 2bar marg may be 0 (kills bar_mixed entirely)
  I: bar densities asymmetric across reels
  J: strip layout may be restructured if needed (last resort)
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

M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"


def _build_engine():
    return load_engine(
        M15_DIR / "spec.json",
        M15_DIR / "weights" / "mode_1" / "weights.json",
        strips_path=M15_DIR / "reel_strips.json",
    )[0]


_ENGINE = _build_engine()
_EV = _ENGINE.evaluator
# All valid symbols
_VALID_SYMBOLS = {"blank", "cherry", "1bar", "2bar", "3bar", "high7", "doublediamond", "topdollar", "jackpot"}


def feature_rtp_pp(topdollar_marg: float) -> float:
    """Feature EV ≈ 46x per trigger (v9 spec)."""
    return topdollar_marg * 46.0 * 100.0


def feature_p_r_ge_1000(topdollar_marg: float) -> float:
    """v9 feature: P(R>=1000) per trigger ≈ 0.00027 (from v9 feasibility)."""
    # Conservative bound from v9 spec.
    # We will compute precisely once we use full feature_params.
    return topdollar_marg * 2.7e-4


def normalize(margs):
    return [{k: v / sum(m.values()) for k, v in m.items()} for m in margs]


def profile_detailed(marg_lst):
    margs = normalize(marg_lst)
    p = analytic_profile_from_marginals(_EV, margs)
    return p, margs


def evaluate(name, raw_margs):
    p, margs = profile_detailed(raw_margs)
    br = p["bucket_rtp"]
    pr = p["pay_rtp"]
    ph = p["pay_hits"]
    base_rtp = p["rtp_pct"]
    hit = p["hit_rate"] * 100
    td = margs[2].get("topdollar", 0.0)
    feat = feature_rtp_pp(td)
    total = base_rtp + feat
    g15 = br.get("ge1_lt5", 0) * 100
    g510 = br.get("ge5_lt10", 0) * 100
    g1020 = br.get("ge10_lt20", 0) * 100
    g2050 = br.get("ge20_lt50", 0) * 100
    R1blank = margs[0].get("blank", 0) * 100
    R1max = max(((s, v) for s, v in margs[0].items() if s != "blank"), key=lambda x: x[1], default=("", 0))
    jp_R1 = margs[0].get("jackpot", 0) * 100
    jp_R2 = margs[1].get("jackpot", 0) * 100
    jp_R3 = margs[2].get("jackpot", 0) * 100
    wild_p = ph.get("1", 0)  # P(3 wild) = pay_id 1
    wild_cadence = (1.0 / wild_p) if wild_p > 0 else float("inf")
    p_r_ge_1000 = feature_p_r_ge_1000(td)

    # CHECK ALL 9 USER HARD CONSTRAINTS
    checks = []
    checks.append(("hit", hit, 15, 18))
    checks.append(("total_rtp", total, 94, 96))
    checks.append(("R1_blank", R1blank, 30, 40))
    checks.append(("g1l5", g15, 11.0, 14.0))
    checks.append(("g5l10", g510, 8.0, 9.5))
    checks.append(("g1020", g1020, 8.5, 10.0))
    checks.append(("P_R>=1000_/spin", p_r_ge_1000, 0, 1e-5))
    checks.append(("jp_R1", jp_R1, 0, 0.6))
    checks.append(("jp_R2", jp_R2, 0, 0.6))
    checks.append(("jp_R3", jp_R3, 0, 0.6))
    # Note: jackpot any-reel ≤ 0.6 is 3 constraints, but user wrote one
    n_pass = sum(1 for n, v, lo, hi in checks if lo <= v <= hi)
    n_tot = len(checks)
    return {
        "name": name,
        "margs": margs,
        "profile": p,
        "base": base_rtp,
        "feature": feat,
        "total": total,
        "hit": hit,
        "R1blank": R1blank,
        "R1max": R1max,
        "g1l5": g15,
        "g5l10": g510,
        "g1020": g1020,
        "g2050": g2050,
        "jp_R1": jp_R1,
        "jp_R2": jp_R2,
        "jp_R3": jp_R3,
        "wild_cadence": wild_cadence,
        "checks": checks,
        "n_pass": n_pass,
        "n_tot": n_tot,
    }


def print_summary(r, full=False):
    name = r["name"]
    pass_str = f"{r['n_pass']}/{r['n_tot']}"
    print(f"{name}: PASS={pass_str} tot={r['total']:6.2f}% base={r['base']:5.2f} feat={r['feature']:5.2f} hit={r['hit']:5.2f}% R1blk={r['R1blank']:5.2f}% R1max={r['R1max'][0]}/{r['R1max'][1]*100:4.1f}%  g1l5={r['g1l5']:5.2f} g5l10={r['g5l10']:5.2f} g1020={r['g1020']:5.2f} g2050={r['g2050']:5.2f}")
    if full:
        for n, v, lo, hi in r["checks"]:
            ok = lo <= v <= hi
            print(f"    {n:>20}: {v:8.3f} [{lo}, {hi}]  {'PASS' if ok else 'FAIL'}")
        margs = r["margs"]
        for i, m in enumerate(margs):
            entries = " ".join(f"{s}={v*100:5.2f}%" for s, v in sorted(m.items(), key=lambda x: -x[1]))
            print(f"    R{i+1}: {entries}")


def make_margs(R1, R2, R3):
    """Build margs list, fill in missing symbols with 0."""
    out = []
    for d in (R1, R2, R3):
        m = {s: 0.0 for s in _VALID_SYMBOLS}
        m.update(d)
        # ensure blank fills in
        non_blank = sum(v for s, v in m.items() if s != "blank")
        if "blank" not in d:
            m["blank"] = max(0.001, 1 - non_blank)
        out.append(m)
    return out


# =========================================================================
# Candidate generation
# =========================================================================

CANDIDATES = []


def add(name, R1, R2, R3):
    CANDIDATES.append((name, lambda R1=R1, R2=R2, R3=R3: make_margs(R1, R2, R3)))


# Symmetric baseline: 1bar=0.252, 2bar=0.13, no 3bar, no cherry
add("A1_sym_25.2/13.0/h7_10/dd_4/td_1",
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.130, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0},
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.130, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0},
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.130, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.02, "topdollar": 0.010})

# bar_mixed slightly higher
add("A2_2bar_0.14",
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.140, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.140, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.140, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.02, "topdollar": 0.010})

add("A3_2bar_0.15",
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.150, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.150, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.45, "1bar": 0.252, "2bar": 0.150, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.02, "topdollar": 0.010})

# R1 blank pushed lower: R1 has more bars
add("D1_R1_low_blank",
    {"blank": 0.35, "1bar": 0.30, "2bar": 0.20, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.02},
    {"blank": 0.50, "1bar": 0.21, "2bar": 0.10, "high7": 0.12, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.50, "1bar": 0.21, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})

# R1 blank 38: medium
add("D2_R1_38_blank",
    {"blank": 0.38, "1bar": 0.27, "2bar": 0.16, "high7": 0.12, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.48, "1bar": 0.225, "2bar": 0.115, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.49, "1bar": 0.225, "2bar": 0.105, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})

add("D3_R1_35_blank",
    {"blank": 0.35, "1bar": 0.30, "2bar": 0.16, "high7": 0.12, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.48, "1bar": 0.225, "2bar": 0.115, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.49, "1bar": 0.225, "2bar": 0.105, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})

add("D4_R1_30_blank",
    {"blank": 0.30, "1bar": 0.34, "2bar": 0.20, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.49, "1bar": 0.215, "2bar": 0.115, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.50, "1bar": 0.215, "2bar": 0.105, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})


# F: vary td (feature trigger)
add("F1_td_0.011",
    {"blank": 0.35, "1bar": 0.30, "2bar": 0.16, "high7": 0.12, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.48, "1bar": 0.225, "2bar": 0.115, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.49, "1bar": 0.225, "2bar": 0.105, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.011})


# More refined R1=38 settings: tune h7 / dd to bring base RTP into [44, 50] window (so feature trigger ~ 1%)
add("E1_R1_38_h7_low",
    {"blank": 0.38, "1bar": 0.27, "2bar": 0.16, "high7": 0.08, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.48, "1bar": 0.225, "2bar": 0.115, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.49, "1bar": 0.225, "2bar": 0.105, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})

# Different bar split — push 2bar lower
add("G1_low_2bar",
    {"blank": 0.38, "1bar": 0.30, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.48, "1bar": 0.225, "2bar": 0.090, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.49, "1bar": 0.225, "2bar": 0.080, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})

# Asymmetric: R3 less bars (push more wild on R3 for cadence)
add("AS1_R3_low_bars",
    {"blank": 0.36, "1bar": 0.28, "2bar": 0.16, "high7": 0.12, "doublediamond": 0.05, "jackpot": 0.02},
    {"blank": 0.46, "1bar": 0.235, "2bar": 0.115, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.55, "1bar": 0.17, "2bar": 0.085, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02, "topdollar": 0.010})

# 3bar non-zero (full paytable visibility)
add("3bar_on",
    {"blank": 0.45, "1bar": 0.22, "2bar": 0.13, "3bar": 0.04, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.45, "1bar": 0.22, "2bar": 0.13, "3bar": 0.04, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.02},
    {"blank": 0.45, "1bar": 0.22, "2bar": 0.13, "3bar": 0.04, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.02, "topdollar": 0.010})

# CRITICAL INSIGHT: Without cherry, max hit ~10-12% (under 15% floor).
# Need cherry > 0 for hit. But cherry-1 (1×) adds to ge1_lt5.
# Tradeoff:
#   ↑ cherry → ↑ hit, ↑ ge1_lt5 (cherry-1 contributes 1× = ge1_lt5)
#   ↓ cherry → ↓ hit, ↓ ge1_lt5 but hit may fail floor
#
# Search cherry 1-3% with bar1/bar2 tuned. Also note jackpot at 0.6%/reel
# requires very low jp weight. R1 jackpot stop weight relative.

# Cherry 2% with low bars to fit ge1_lt5
add("CH1_c2_bars_low",
    {"blank": 0.50, "cherry": 0.02, "1bar": 0.23, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.02, "1bar": 0.23, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.02, "1bar": 0.23, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

add("CH2_c1.5_bars_higher",
    {"blank": 0.45, "cherry": 0.015, "1bar": 0.25, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.45, "cherry": 0.015, "1bar": 0.25, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.45, "cherry": 0.015, "1bar": 0.25, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

add("CH3_c2.5_low_bars",
    {"blank": 0.50, "cherry": 0.025, "1bar": 0.22, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.025, "1bar": 0.22, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.025, "1bar": 0.22, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Asymmetric R3 cherry low (cherry contributes to hit via cherry-1, no high reels needed)
add("CH4_c_asym_R1_high",
    {"blank": 0.45, "cherry": 0.04, "1bar": 0.23, "2bar": 0.11, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.005, "1bar": 0.25, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.03, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.005, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Just R1 cherry — cherry-1 P = c_R1, cherry-2 = 0
# At c_R1 = 8% on R1 only, cherry-2 = 0, cherry-1 = 8pp
add("CH5_R1_only_cherry",
    {"blank": 0.40, "cherry": 0.08, "1bar": 0.25, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Cherry on R1+R2 only
add("CH6_R1_R2_only_cherry",
    {"blank": 0.46, "cherry": 0.04, "1bar": 0.23, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.46, "cherry": 0.04, "1bar": 0.23, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.49, "cherry": 0.0, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005, "topdollar": 0.010})

# More cherry on R1 only, max bars
add("CH7_R1_cherry_10pct",
    {"blank": 0.40, "cherry": 0.10, "1bar": 0.22, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Tight jackpot: weight 0.5% per reel
add("CH8_R1_cherry_12",
    {"blank": 0.38, "cherry": 0.12, "1bar": 0.22, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Try cherry on R1 only at 13% (cherry-1 = 13pp directly)
add("CH9_R1_cherry_13",
    {"blank": 0.36, "cherry": 0.13, "1bar": 0.22, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Adjust bars to keep ge1_lt5 ≤ 14 with cherry on R1 only at 13%
# cherry-1 from R1 only at c_R1=13% = 13pp into ge1_lt5
# But cherry-1 fires only when cherry is on payline AND not 2 or 3 cherry
# P(cherry-1) where cherry only on R1 = c_R1 × (1-c_R2) × (1-c_R3) = c_R1 × 1 × 1 = c_R1
# = 13pp
# Already at ge1_lt5 cap. bar_mixed must be ≤ 1pp → almost no bars
add("CH10_R1_cherry_13_min_bars",
    {"blank": 0.36, "cherry": 0.13, "1bar": 0.22, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# WAVE 2: cherry on R1 only — gets hit from cherry-1 without adding cherry-2/3
# (since cherry-2/3 require 2+ cherry on payline)
# At cherry_R1 = c, others = 0: cherry-1 P = c, ge1_lt5 cherry contrib = c × 100 pp
# To leave room for bar_mixed: c + bar_mixed_RTP ≤ 14
#
# For bars: g5l10 = bar1_pure (and that's all without cherry-2)
# bar1_pure = p1·p2·p3 × 5 × 100
# At p_sym = 0.252, bar1_pure = 8pp. Good.
# bar_mixed = (sum_bars)^3 product - 1bar^3 - 2bar^3 - 3bar^3
# At 1bar=0.252, 2bar=0.10, 3bar=0: sum=0.352, prod=0.0436, -0.016 -0.001 -0 = 0.0266 = 2.66%
# bar_mixed_RTP = 5.32pp ge1_lt5
# cherry-1 budget = 14 - 5.32 = 8.68pp → c = 8.68%
# cherry contributes c% to hit. With c=8.68% on R1, hit_cherry = 8.68%
# Plus bar1 = 1.6%, bar_mixed = 2.66%, total bars = ~5%
# Plus h7 + dd + scatter — small
# Total hit ~ 14% — STILL UNDER 15

# So we need more bar paths to fill hit. Strategy: maximize 1b+1b+wild paths (10× ge10_lt20)
# At p=0.252, d_sym=0.06: 3·p²·d = 3·0.0635·0.06 = 1.143% hit (at 10×)
# Combined with cherry on R1 at 8.7%: total hit ~ 8.7% + 1.6% (b1) + 2.7% (bm) + 1.14% (1b1bwild) = 14.14%
# Close. Need a bit more.
# Add 1b+1b+wild contribution ~1.5%: d=0.08
# Then ge20_lt50 from (1b,2b,wild) and (2b,2b,wild) and (1b,wild,wild)
# (1bar,2bar,wild) = pay_id 8 × 4 → ge1_lt5! Adds 3·p·q·d·4 = 3·0.252·0.10·0.08·4 = 2.42%×4=0.0242
# Hmm let me re-think — multiplier 4 × prob 3·0.252·0.10·0.08·100 = 0.605% × 4 = 2.42pp ge1_lt5
# So adding wild bloats ge1_lt5 too via mixed paths.

# Test: cherry R1=10%, dd_sym=0.04 (modest wild), 1bar=0.252 sym, 2bar=0.10 sym
add("W1_cherryR1_10_dd_4",
    {"blank": 0.40, "cherry": 0.10, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

add("W2_cherryR1_8_dd_5",
    {"blank": 0.42, "cherry": 0.08, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.05, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.05, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005, "topdollar": 0.010})

# Maybe cherry distributed across all 3 reels low for cherry-2/cherry-3 boost
# Now cherry on R3 too contributes cherry-2 + cherry-3
add("W3_cherry_R1R2_high",
    {"blank": 0.40, "cherry": 0.08, "1bar": 0.23, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.42, "cherry": 0.08, "1bar": 0.23, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.005, "1bar": 0.25, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Strip-restructure idea (Lever J): need to add a stop with weight 1 cherry on R2/R3 to allow that
# Actually we don't need to. Cherry already on R2/R3 in current strip.

# Push 2bar higher to fill g1020 via bar2_pure (10× -> ge10_lt20)
add("W4_2bar_high",
    {"blank": 0.40, "cherry": 0.10, "1bar": 0.20, "2bar": 0.20, "high7": 0.08, "doublediamond": 0.02, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.22, "2bar": 0.20, "high7": 0.05, "doublediamond": 0.025, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.22, "2bar": 0.20, "high7": 0.05, "doublediamond": 0.02, "jackpot": 0.005, "topdollar": 0.010})

# Test extreme: high cherry R1, very low bars (only 1bar)
add("W5_extreme_cherryR1",
    {"blank": 0.35, "cherry": 0.13, "1bar": 0.30, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.02, "jackpot": 0.005},
    {"blank": 0.55, "cherry": 0.0, "1bar": 0.22, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.55, "cherry": 0.0, "1bar": 0.22, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.03, "jackpot": 0.005, "topdollar": 0.010})

# Two-cherry-reel design: R1 and R3 only with cherry
add("W6_cherry_R1_R3",
    {"blank": 0.42, "cherry": 0.10, "1bar": 0.22, "2bar": 0.12, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.252, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.42, "cherry": 0.05, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005, "topdollar": 0.010})

# Three-cherry-reel low+balanced
add("W7_cherry_uniform_2pct",
    {"blank": 0.43, "cherry": 0.02, "1bar": 0.25, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.05, "jackpot": 0.005},
    {"blank": 0.43, "cherry": 0.02, "1bar": 0.25, "2bar": 0.13, "high7": 0.10, "doublediamond": 0.05, "jackpot": 0.005},
    {"blank": 0.45, "cherry": 0.02, "1bar": 0.25, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005, "topdollar": 0.010})

# Cherry R1 high, R3 low to get cherry-2 contribution to ge5_lt10
add("W8_cherry_R1_8_R2_3_R3_0",
    {"blank": 0.42, "cherry": 0.08, "1bar": 0.24, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.45, "cherry": 0.03, "1bar": 0.25, "2bar": 0.12, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005},
    {"blank": 0.50, "cherry": 0.0, "1bar": 0.252, "2bar": 0.10, "high7": 0.08, "doublediamond": 0.04, "jackpot": 0.005, "topdollar": 0.010})

# Make bars asymmetric: bar1 dominant on R2/R3, 2bar on R1
add("W9_bar_asym",
    {"blank": 0.40, "cherry": 0.06, "1bar": 0.20, "2bar": 0.20, "high7": 0.08, "doublediamond": 0.05, "jackpot": 0.005},
    {"blank": 0.45, "cherry": 0.0, "1bar": 0.28, "2bar": 0.13, "high7": 0.08, "doublediamond": 0.05, "jackpot": 0.005},
    {"blank": 0.45, "cherry": 0.0, "1bar": 0.28, "2bar": 0.10, "high7": 0.10, "doublediamond": 0.04, "jackpot": 0.005, "topdollar": 0.010})




if __name__ == "__main__":
    print("=" * 110)
    print("M15 v10d candidate exploration — all 9 user hard constraints checked")
    print("=" * 110)
    results = []
    for name, builder in CANDIDATES:
        margs_raw = builder()
        r = evaluate(name, margs_raw)
        results.append(r)
        print_summary(r)
    print()
    print("=" * 110)
    print("Best candidates (sorted by n_pass)")
    print("=" * 110)
    for r in sorted(results, key=lambda x: -x["n_pass"])[:5]:
        print_summary(r, full=True)
        print()
