"""M15 v14 mode 1 — ARCHETYPE-FIRST redesign (2026-05-12 wave 14, post v8 hardline shift).

User v8 directive (2026-05-12): "完全不行。换思路重新来过。保留feature配置不变，
只变normal spin。放开所有rtp分桶的限制。只满足reel体验和rtp构成的合理性。"

All ge*_lt* bucket bands DROPPED. New direction: classic 7-bar slot ARCHETYPE
with REASONABLE rtp composition. Think GAME, not bucket-math.

Hard constraints (only these remain):
  H1: Paytable byte-equal (spec.json pays block)
  H2: feature_params byte-equal v9 (locked)
  H3: Strip layout unchanged (36 stops per reel, blank/non-blank alternation)
  H4: Total RTP ∈ [94, 96]pp
  H5: Hit session ∈ [15, 18]% (incl feature trigger 1.1%)
  H6: R1 blank marginal ∈ [30%, 40%]
  H7: Jackpot per-reel marginal ≤ 0.6%
  H8: Avoid 1000× bet+ rewards (qualitative — wild_pure 200× OK; jackpot
      1000× is reroll-blocked)

Qualitative archetypal direction:
  Reel experience reasonable:
    - All 6 paying families (cherry/1bar/2bar/3bar/high7/dd) visible per reel,
      each ≥ ~2-3% marginal
    - No family marginal > ~25-30% per reel (visual balance)
    - Strip alternation preserved

  RTP composition reasonable:
    - Each pay_id fires ≥ 1/10000 spins
    - Bar hierarchy: P(bar1_pure) > P(bar2_pure) > P(bar3_pure)
    - cherry-2 P ≥ ~0.3%, cherry-3 P ≥ ~0.01%
    - wild_pure cadence 1 per 50k-100k spins
    - No family share-of-base > ~25-28% (avoid pareto trap)
    - Avoid extreme R1 vs R3 asymmetry (keep within reasonable pyramid)

Classical IGT archetype baseline (RWB / Blazing Sevens / Double Diamond):
    cherry per reel:   3-6%
    1bar per reel:    12-20%
    2bar per reel:     8-15%
    3bar per reel:     5-10%
    high7 per reel:    3-8%
    dd per reel:       2-4%
    jp per reel:       0.3-0.5%
    topdollar R3:      1.1% (locked feature trigger rate)

Approach: start from RWB-style proportions, vary key knobs (cherry density,
which bar family slightly dominates, h7 density, dd density, R1↔R3 gradient),
build 12 candidates. Evaluate each on archetypal fitness, not bucket math.
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

# Load engine ONCE (we don't mutate weights — just borrow evaluator)
engine, _spec = load_engine(SPEC_PATH, WEIGHTS_PATH, strips_path=STRIPS_PATH)
EV = engine.evaluator
STRIPS = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]

# Load feature_params (LOCKED v9, byte-equal)
fp = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))["feature_params"]

# Precompute feature per-bucket EV (locked feature_params)
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
for r, p in final_dist.items():
    b = to_bucket(r)
    if b:
        FEAT_BUCKET_EV[b] += r * p
FEAT_EV_TOTAL = sum(FEAT_BUCKET_EV.values())


PAY_FAM_MAP = {
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


def make_marginals(R1, R2, R3):
    """Normalize 3 dicts to per-reel probability distributions (blank = residual)."""
    out = []
    for R in (R1, R2, R3):
        R = dict(R)
        non_blank = sum(R.values())
        R["blank"] = max(0.001, 1.0 - non_blank)
        s = sum(R.values())
        out.append({k: v / s for k, v in R.items() if v > 0})
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
    return table, weights


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
        "r1_blank": margs[0].get("blank", 0) * 100,
        "r2_blank": margs[1].get("blank", 0) * 100,
        "r3_blank": margs[2].get("blank", 0) * 100,
        "session_bucket": session_bucket,
        "pay_hits": prof["pay_hits"],
        "pay_rtp": pay_rtp,
        "family_pp": dict(family_pp),
        "high7_combined_pp": high7_combined_pp,
        "family_shares": family_shares,
        "wild_cadence": wild_cadence,
        "margs": margs,
        "cv": prof["cv"],
    }


def check_hardlines(r):
    """Check ONLY user v8 hardlines (no bucket bands)."""
    checks = []

    def chk(name, val, lo, hi):
        ok = lo <= val <= hi
        checks.append((name, val, "PASS" if ok else "FAIL", (lo, hi)))

    chk("H4 total_rtp", r["total_rtp"], 94, 96)
    chk("H5 hit_session", r["hit_session"], 15, 18)
    chk("H6 R1_blank", r["r1_blank"], 30, 40)
    for i, m in enumerate(r["margs"]):
        chk(f"H7 R{i+1}_jp", m.get("jackpot", 0) * 100, 0, 0.6)
    return checks


def archetype_audit(r):
    """Audit archetypal direction. Returns a list of (label, value, judgment, note)."""
    out = []
    fs = r["family_shares"]
    margs = r["margs"]
    pay_hits = r["pay_hits"]

    # Family share — no family > 28%
    for fam in ("cherry1", "high7", "bar1", "bar_mixed"):
        share = fs.get(fam, 0)
        judg = "OK" if share <= 28 else "DOMINANT"
        out.append(("family_share_" + fam, share, judg, "<= 28%"))
    # Each family below 5% means below floor (a few smalls are OK)
    for fam in ("bar2", "bar3", "wild_pure", "cherry2"):
        share = fs.get(fam, 0)
        judg = "OK" if share >= 1.0 else "SLIM"
        out.append(("family_share_" + fam, share, judg, ">= 1%"))

    # Each pay_id fires >= 1/10000 (0.01% hit)
    for pid, fam in PAY_FAM_MAP.items():
        p = pay_hits.get(pid, 0) * 100
        if pid == "1":  # wild_pure target is 1/50k-100k (so 0.001-0.002%)
            judg = "OK" if 50000 <= (1/(p/100) if p > 0 else float("inf")) <= 100000 else "DRIFT"
            out.append((f"pay_{pid}_{fam}_hit%", p, judg, "1/50k-100k"))
        elif pid in ("4", "3", "5"):
            # cherry-3, bar3_pure, bar2_pure — rare but should fire >= 1/10000
            judg = "OK" if p >= 0.01 else "DEAD"
            out.append((f"pay_{pid}_{fam}_hit%", p, judg, ">= 0.01% (1/10k)"))
        else:
            judg = "OK"
            out.append((f"pay_{pid}_{fam}_hit%", p, judg, "active"))

    # Bar hierarchy P(bar1_pure) > P(bar2_pure) > P(bar3_pure)
    p_b1 = pay_hits.get("7", 0)
    p_b2 = pay_hits.get("5", 0)
    p_b3 = pay_hits.get("3", 0)
    hier_ok = p_b1 > p_b2 > p_b3
    out.append(("bar_hierarchy", f"{p_b1*100:.4f}>{p_b2*100:.4f}>{p_b3*100:.4f}",
                "OK" if hier_ok else "INVERTED", "monotone"))

    # Visual: each family non-trivially visible per reel
    families_to_check = ["cherry", "1bar", "2bar", "3bar", "high7", "doublediamond"]
    for fam in families_to_check:
        min_m = min(margs[i].get(fam, 0) * 100 for i in range(3))
        max_m = max(margs[i].get(fam, 0) * 100 for i in range(3))
        judg = "OK" if min_m >= 2.0 and max_m <= 30.0 else ("THIN" if min_m < 2 else "DOMINANT")
        out.append((f"vis_{fam}_minmax%", f"{min_m:.2f}/{max_m:.2f}", judg, ">=2% & <=30%"))

    # Reel asymmetry: R1 blank lower than R3 blank
    asym = r["r3_blank"] - r["r1_blank"]
    judg = "OK" if asym >= 0 else "INVERTED"
    out.append(("r3_minus_r1_blank", f"{asym:.2f}pp", judg, ">=0"))

    # CV (informational)
    out.append(("base_cv", f"{r['cv']:.3f}", "INFO", "informational"))

    return out


def fmt_marg(m):
    return ", ".join(f"{k}={v*100:.2f}%" for k, v in sorted(m.items(), key=lambda x: -x[1]))


def report(name, r, *, verbose=True):
    checks = check_hardlines(r)
    n_fail = sum(1 for _, _, st, _ in checks if st == "FAIL")
    audit = archetype_audit(r)
    fs = r["family_shares"]

    if verbose:
        print(f"\n======== Candidate: {name} ========")
        print(f"  total_rtp={r['total_rtp']:.3f}pp (base={r['base_rtp']:.2f}pp + feat={r['feature_rtp']:.2f}pp)")
        print(f"  hit_session={r['hit_session']:.3f}% (base={r['base_hit']:.2f}% + trigger={r['trigger']:.2f}%)")
        print(f"  R1_blank={r['r1_blank']:.2f}%  R2_blank={r['r2_blank']:.2f}%  R3_blank={r['r3_blank']:.2f}%")
        print(f"  wild_cadence=1/{r['wild_cadence']:.0f}")
        print(f"  hardline FAILs={n_fail}")
        for nm, val, st, band in checks:
            print(f"    {nm}: {val:.3f}  band={band}  [{st}]")
        print(f"  family_shares:")
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "high7", "wild_pure"):
            v = fs.get(fam, 0)
            print(f"    {fam}: {v:.2f}%")
        print(f"  archetype audit (DOMINANT/DEAD/SLIM/INVERTED = soft concerns):")
        notable = [a for a in audit if a[2] not in ("OK", "INFO")]
        for nm, val, st, note in notable:
            print(f"    {nm}: {val}  [{st}] ({note})")
        print(f"  session buckets (record only, no targets):")
        for k in sorted(r["session_bucket"].keys(), key=lambda k: -[e[0] for e in _BUCKET_EDGES if e[1] == k][0]):
            v = r["session_bucket"].get(k, 0)
            print(f"    {k}: {v:.3f}pp")
    return {"checks": checks, "audit": audit, "n_fail": n_fail}


# -----------------------------------------------------------------------
# Candidates — classical archetype-first design exploration
# -----------------------------------------------------------------------
#
# All candidates anchored to classical IGT/RWB-style proportions, then
# tuned to fit M15's paytable + 8 hardlines. Goal: each family visible,
# no single family dominates, all pays fire, R1 winners-friendly.
#
# M15 paytable structural notes:
# - cherry-anywhere (1×) anchors cherry-1 hit (frequent low pay)
# - bar_mixed (any 3 bars = 2×) is high-frequency mid-low pay
# - bar1 (5×), bar2 (10×), bar3 (20×) — classical 4-5-10× progression × 2-4×
# - high7 PURE (30×) + high7+wild (30× w/ wild substitution boost to 60/120)
# - wild_pure (3 dd = 200×) is top pay band (low cadence)
# - cherry-3 (3 cherry = 15×) — rare classic
# - topdollar locked on R3 at ~1.1% (feature trigger)
# - jackpot decorative filler (reroll-blocked)


def C1_classic_balanced():
    """C1: Classic balanced. Push non-blank density up so R1 blank ~38%.

    R1 non-blank 62% (cherry 4.5 + 1bar 22 + 2bar 17 + 3bar 9 + h7 6 + dd 3 + jp 0.4).
    R2 non-blank ~55%. R3 non-blank ~48% (incl topdollar 1.1).
    """
    R1 = {"cherry": 0.045, "1bar": 0.220, "2bar": 0.170, "3bar": 0.090,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.190, "2bar": 0.145, "3bar": 0.075,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.028, "1bar": 0.160, "2bar": 0.120, "3bar": 0.060,
          "high7": 0.040, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C2_low_cherry():
    """C2: Lower cherry density, classic 7-bar slot. R1 non-blank ~63%.
    Cherry 3.0/3.0/2.0, bar1 22/19/16, bar2 18/15/12, bar3 11/9/7, h7 6/5/4."""
    R1 = {"cherry": 0.030, "1bar": 0.220, "2bar": 0.180, "3bar": 0.110,
          "high7": 0.060, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.190, "2bar": 0.150, "3bar": 0.090,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.160, "2bar": 0.120, "3bar": 0.070,
          "high7": 0.040, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C3_high_cherry_low_h7():
    """C3: Higher cherry (5%) + reduced high7 (4/3/2.5). R1 non-blank ~62%.
    Cherry hits drive hit_session toward 17%. bar tier 21/18/15."""
    R1 = {"cherry": 0.050, "1bar": 0.210, "2bar": 0.170, "3bar": 0.090,
          "high7": 0.040, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.180, "2bar": 0.140, "3bar": 0.080,
          "high7": 0.035, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.155, "2bar": 0.115, "3bar": 0.060,
          "high7": 0.025, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C4_bar_dominant_classic():
    """C4: Bar-family heavier (classic IGT bar slot ratios). R1 non-blank ~63%.
    Per RWB: bar 31% of RTP. bar1 21/18/15, bar2 19/16/13, bar3 11/9/7.
    Cherry 3.5/3/2.5, h7 4/3.5/3."""
    R1 = {"cherry": 0.035, "1bar": 0.210, "2bar": 0.190, "3bar": 0.110,
          "high7": 0.040, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.180, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.035, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.150, "2bar": 0.130, "3bar": 0.070,
          "high7": 0.025, "doublediamond": 0.023, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C5_high_h7_balanced():
    """C5: h7 lifted (7/6/5) - classic seven feel. R1 non-blank ~62%.
    Bars moderate to compensate."""
    R1 = {"cherry": 0.040, "1bar": 0.190, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.070, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.075,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.140, "2bar": 0.115, "3bar": 0.060,
          "high7": 0.050, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C6_RWB_proportions():
    """C6: RWB proportions scaled to M15 + density-corrected.
    cherry 16% / bar 31% / h7 50% of base ~ 43pp. R1 non-blank ~63%.
    Higher h7 to match seven-heavy classic; bars also visible."""
    R1 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.140, "3bar": 0.080,
          "high7": 0.090, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.145, "2bar": 0.120, "3bar": 0.070,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.120, "2bar": 0.100, "3bar": 0.055,
          "high7": 0.060, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C7_double_diamond_style():
    """C7: Double Diamond style — dd visible (4/4/3), bars moderate.
    Cherry 4/3.5/2.5, bar1 19/16/13, bar2 16/14/11, bar3 9/7/6, h7 4/3.5/3, dd 4/4/3."""
    R1 = {"cherry": 0.040, "1bar": 0.190, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.040, "doublediamond": 0.040, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.140, "3bar": 0.075,
          "high7": 0.035, "doublediamond": 0.038, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.140, "2bar": 0.115, "3bar": 0.060,
          "high7": 0.030, "doublediamond": 0.030, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C8_symmetric():
    """C8: Symmetric reels (mild R1↔R3 gradient). R1 non-blank ~61%.
    Cherry 4/4/3, bar1 19/17/14, bar2 16/14/11, bar3 9/8/6, h7 5/5/4, dd 3.2/3/2.5."""
    R1 = {"cherry": 0.040, "1bar": 0.190, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.140, "3bar": 0.080,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.140, "2bar": 0.115, "3bar": 0.060,
          "high7": 0.040, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C9_stronger_asymmetry():
    """C9: Stronger R1 vs R3 gradient (winners-friendly).
    R1 non-blank 68%, R3 non-blank 45%. Cherry 5/3.5/2."""
    R1 = {"cherry": 0.050, "1bar": 0.230, "2bar": 0.190, "3bar": 0.110,
          "high7": 0.060, "doublediamond": 0.035, "jackpot": 0.005}
    R2 = {"cherry": 0.035, "1bar": 0.180, "2bar": 0.150, "3bar": 0.085,
          "high7": 0.045, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.020, "1bar": 0.130, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.030, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C10_low_RTP_floor_aim():
    """C10: aim for total RTP ~94.3 (lower edge safety). R1 non-blank 60%.
    Reduce bars slightly so RTP lands lower in band."""
    R1 = {"cherry": 0.040, "1bar": 0.190, "2bar": 0.150, "3bar": 0.080,
          "high7": 0.055, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.125, "3bar": 0.065,
          "high7": 0.045, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.105, "3bar": 0.055,
          "high7": 0.035, "doublediamond": 0.023, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C11_cherry_heavy_hit():
    """C11: Cherry-heavy (5/4.5/3) to lift hit session toward upper band.
    Bars moderate (19/17/13). h7 5/4/3. dd 3/2.8/2.4."""
    R1 = {"cherry": 0.050, "1bar": 0.190, "2bar": 0.160, "3bar": 0.085,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.045, "1bar": 0.165, "2bar": 0.135, "3bar": 0.075,
          "high7": 0.040, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.030, "doublediamond": 0.024, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C12_balanced_no_dominant():
    """C12: explicitly balanced family share targets (cherry1~22%, bar1~22%,
    h7~18%, bar_mixed~18%, bar2/bar3 visible). R1 non-blank ~62%.
    Cherry 4.5/4/2.5, 1bar 19/17/14, 2bar 16/14/11, 3bar 9/7/5, h7 5/4/3, dd 3/3/2.5."""
    R1 = {"cherry": 0.045, "1bar": 0.190, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.140, "3bar": 0.070,
          "high7": 0.040, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.140, "2bar": 0.110, "3bar": 0.050,
          "high7": 0.030, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C13_high7_classic_seven():
    """C13: classic 7-symbol seven-heavy. high7 7/6/5 + slight dd lift to 3.2.
    Bars moderate, cherry restrained 3.5/3/2.5."""
    R1 = {"cherry": 0.035, "1bar": 0.180, "2bar": 0.150, "3bar": 0.085,
          "high7": 0.070, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.030, "1bar": 0.155, "2bar": 0.130, "3bar": 0.075,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.060,
          "high7": 0.050, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C14_C5_refined():
    """C14: C5 refined — push R1 blank below 40 by adding bar3 R1 to 11
    and bar1 R1 to 20. Reduce slightly to keep RTP in band."""
    R1 = {"cherry": 0.040, "1bar": 0.200, "2bar": 0.165, "3bar": 0.105,
          "high7": 0.070, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.075,
          "high7": 0.055, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.045, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C15_C13_refined():
    """C15: C13 7-heavy refined — boost density for R1 < 40, trim RTP."""
    R1 = {"cherry": 0.040, "1bar": 0.200, "2bar": 0.160, "3bar": 0.095,
          "high7": 0.075, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.075,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.050, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C16_balanced_target():
    """C16: explicitly target each family share to ~15-25% range.
    Mid h7 (5%/4%/3%), restrained bars (16/14/12 ; 14/12/10 ; 8/7/5).
    Cherry 4/3.5/2.5."""
    R1 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.145, "3bar": 0.085,
          "high7": 0.060, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.145, "2bar": 0.120, "3bar": 0.070,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.125, "2bar": 0.100, "3bar": 0.055,
          "high7": 0.040, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C17_seven_heavy_lower_bars():
    """C17: 7-heavy slot with reduced bar density. h7 7/6/5, lower bar1.
    Cherry 4/3.5/2.5, bar1 17/14/12, bar2 14/12/10, bar3 8/7/5."""
    R1 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.140, "3bar": 0.080,
          "high7": 0.070, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.140, "2bar": 0.120, "3bar": 0.070,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.120, "2bar": 0.100, "3bar": 0.050,
          "high7": 0.050, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C18_C12_refined():
    """C18: C12 balanced but lower R1 blank to ≤40. cherry 4.5/4/2.5,
    bar1 19/17/14, bar2 16/14/11, bar3 9/7/5, h7 5/4/3, dd 3/3/2.5.
    Add R1 density to push blank below 40."""
    R1 = {"cherry": 0.045, "1bar": 0.200, "2bar": 0.170, "3bar": 0.095,
          "high7": 0.055, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.140, "3bar": 0.075,
          "high7": 0.045, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.140, "2bar": 0.110, "3bar": 0.050,
          "high7": 0.035, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C19_C14_fix_cherry3_cadence():
    """C19: C14 refined further — cherry up to 5/4/3 to lift cherry-3 freq;
    dd up to 3.5/3.5/3 to bring wild_pure cadence into 50k-100k band."""
    R1 = {"cherry": 0.050, "1bar": 0.190, "2bar": 0.160, "3bar": 0.100,
          "high7": 0.060, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.160, "2bar": 0.130, "3bar": 0.075,
          "high7": 0.050, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.130, "2bar": 0.105, "3bar": 0.055,
          "high7": 0.040, "doublediamond": 0.030, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C20_C14_seven_anchor():
    """C20: C14 with slightly higher h7 (7.5/6/5) for classic 7 anchor;
    dd slight lift for cadence."""
    R1 = {"cherry": 0.045, "1bar": 0.195, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.075, "doublediamond": 0.033, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.160, "2bar": 0.130, "3bar": 0.070,
          "high7": 0.060, "doublediamond": 0.032, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.130, "2bar": 0.105, "3bar": 0.055,
          "high7": 0.050, "doublediamond": 0.027, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C21_lift_dd_for_cadence():
    """C21: C14 base + dd lifted significantly to 3.5/3.5/3.0 (5% of dd
    cubed = 1/100k+) — push wild_pure cadence into band."""
    R1 = {"cherry": 0.040, "1bar": 0.195, "2bar": 0.160, "3bar": 0.100,
          "high7": 0.065, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.160, "2bar": 0.130, "3bar": 0.075,
          "high7": 0.055, "doublediamond": 0.035, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.130, "2bar": 0.105, "3bar": 0.055,
          "high7": 0.045, "doublediamond": 0.028, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C22_balanced_v2():
    """C22: balance bar_mixed below 25% by reducing 3-bar density.
    Goal: cherry1 ~21%, bar_mixed ~22%, bar1 ~15%, h7 ~10%, bar2 ~14%, bar3 ~8%."""
    R1 = {"cherry": 0.040, "1bar": 0.180, "2bar": 0.140, "3bar": 0.080,
          "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.150, "2bar": 0.115, "3bar": 0.065,
          "high7": 0.065, "doublediamond": 0.032, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.125, "2bar": 0.095, "3bar": 0.050,
          "high7": 0.055, "doublediamond": 0.026, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C23_C20_rtp_trim():
    """C23: C20 but trim bar2 slightly to drop RTP below 96 cap.
    Also higher cherry for cherry3 freq."""
    R1 = {"cherry": 0.050, "1bar": 0.195, "2bar": 0.150, "3bar": 0.090,
          "high7": 0.075, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.160, "2bar": 0.125, "3bar": 0.070,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.130, "2bar": 0.100, "3bar": 0.055,
          "high7": 0.050, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C24_balanced_seven_cherry():
    """C24: balanced classic, slight 7 anchor, cherry visible.
    Cherry 4.5/4/3 (cherry3 ~ 0.005% = 1/20k), h7 7/6/5, dd 3.2/3/2.6."""
    R1 = {"cherry": 0.045, "1bar": 0.185, "2bar": 0.150, "3bar": 0.085,
          "high7": 0.070, "doublediamond": 0.032, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.155, "2bar": 0.125, "3bar": 0.070,
          "high7": 0.060, "doublediamond": 0.030, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.130, "2bar": 0.105, "3bar": 0.055,
          "high7": 0.050, "doublediamond": 0.026, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C25_top_h7_classic():
    """C25: high7 as top mid-pay (8/7/6) classic seven-heavy slot.
    Cherry 4/3.5/2.5, bar1 17/14/12, bar2 14/12/10, bar3 8/7/5, dd 3/2.8/2.5."""
    R1 = {"cherry": 0.040, "1bar": 0.170, "2bar": 0.140, "3bar": 0.080,
          "high7": 0.080, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.140, "2bar": 0.120, "3bar": 0.070,
          "high7": 0.070, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.120, "2bar": 0.100, "3bar": 0.050,
          "high7": 0.060, "doublediamond": 0.025, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C26_C20_clean():
    """C26: C20 with cadence drop. dd 3/2.8/2.4 (lift cadence band toward 50k-80k).
    Cherry 4.5/3.5/2.5, bar1 19/16/13, bar2 16/13/10, bar3 9/7/5, h7 7.5/6/5."""
    R1 = {"cherry": 0.045, "1bar": 0.190, "2bar": 0.155, "3bar": 0.088,
          "high7": 0.075, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.158, "2bar": 0.128, "3bar": 0.068,
          "high7": 0.060, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.128, "2bar": 0.102, "3bar": 0.052,
          "high7": 0.048, "doublediamond": 0.024, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C27_recommended():
    """C27: C20 with RTP trimmed below 96 cap + dd dialed down for
    cadence in band [50k, 100k]. Aim: best family balance + all hardlines green.

    cherry 4.5/3.5/2.5 (cherry3 ~ 0.005% = 1/25k — visible per 25k spin)
    bar1 19/16/13 — 14% family share
    bar2 16/13/10 — 15% family share
    bar3 9/7/5 — 9% family share
    high7 7/6/5 — 10% family share (classic seven anchor)
    dd 2.8/2.6/2.2 — wild_pure cadence ~ 1/55k (IN band)
    jp 0.4/0.4/0.3
    td R3 0.0113 (locked feature trigger)
    """
    R1 = {"cherry": 0.045, "1bar": 0.190, "2bar": 0.155, "3bar": 0.085,
          "high7": 0.070, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.160, "2bar": 0.128, "3bar": 0.068,
          "high7": 0.060, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.128, "2bar": 0.100, "3bar": 0.050,
          "high7": 0.050, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C28_recommended_v2():
    """C28: like C27 but cherry slightly bumped to 5/4/3 for cherry3 in 1/15k."""
    R1 = {"cherry": 0.050, "1bar": 0.190, "2bar": 0.150, "3bar": 0.082,
          "high7": 0.068, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.155, "2bar": 0.125, "3bar": 0.065,
          "high7": 0.058, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.125, "2bar": 0.098, "3bar": 0.048,
          "high7": 0.048, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C29_lower_h7():
    """C29: lower h7 (5/4.5/4) to avoid h7 family share dominance.
    Bars and cherry are the centerpiece."""
    R1 = {"cherry": 0.045, "1bar": 0.200, "2bar": 0.160, "3bar": 0.090,
          "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.165, "2bar": 0.135, "3bar": 0.073,
          "high7": 0.045, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.108, "3bar": 0.055,
          "high7": 0.040, "doublediamond": 0.023, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C30_minimal_diamond_balanced():
    """C30: Double-Diamond style with strong bars + visible dd.
    bars 19/16/14, h7 5/4.5/4, dd 3.5/3.2/2.8, cherry 4.5/4/2.5."""
    R1 = {"cherry": 0.045, "1bar": 0.190, "2bar": 0.155, "3bar": 0.085,
          "high7": 0.050, "doublediamond": 0.035, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.158, "2bar": 0.128, "3bar": 0.070,
          "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.130, "2bar": 0.105, "3bar": 0.052,
          "high7": 0.040, "doublediamond": 0.028, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C31_C14_cadence_fix():
    """C31: C14 with dd reduced to lift cadence into 50-100k band.
    Keep everything else from C14. dd 0.028/0.028/0.022 instead of 0.030/0.030/0.025.

    Expected: cadence ~ 1/(0.028*0.028*0.022) = ~1/57k IN band.
    Bar2 +0.5pp on R1 to keep R1 blank under 40 (since dd dropped a hair).
    """
    R1 = {"cherry": 0.040, "1bar": 0.200, "2bar": 0.170, "3bar": 0.105,
          "high7": 0.070, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.075,
          "high7": 0.055, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.045, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C32_C14_cherry_lift():
    """C32: C14 with cherry lifted 5/4/3 (cherry3 1/15k+) + dd at 2.8/2.7/2.2 (cad in band).
    Adjust bars to bring RTP back in band."""
    R1 = {"cherry": 0.050, "1bar": 0.195, "2bar": 0.165, "3bar": 0.100,
          "high7": 0.065, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.160, "2bar": 0.130, "3bar": 0.072,
          "high7": 0.055, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.130, "2bar": 0.108, "3bar": 0.052,
          "high7": 0.045, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C33_anchor_classic():
    """C33: balanced classic anchor - cherry, bar1, bar_mixed each ~20% share.
    No single family over 25%. dd dialed for cadence."""
    R1 = {"cherry": 0.045, "1bar": 0.195, "2bar": 0.155, "3bar": 0.092,
          "high7": 0.068, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.038, "1bar": 0.162, "2bar": 0.130, "3bar": 0.072,
          "high7": 0.055, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.133, "2bar": 0.105, "3bar": 0.053,
          "high7": 0.045, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C34_C20_no_dominance():
    """C34: C20 with bar_mixed reduced (drop 3bar density) + RTP tuning.
    Goal: max family ≤ 25%, RTP 94.5-95.5, cadence 1/50-100k."""
    R1 = {"cherry": 0.045, "1bar": 0.190, "2bar": 0.155, "3bar": 0.075,
          "high7": 0.080, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.158, "2bar": 0.130, "3bar": 0.062,
          "high7": 0.065, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.128, "2bar": 0.105, "3bar": 0.045,
          "high7": 0.055, "doublediamond": 0.023, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C35_C14_bar3_trim():
    """C35: C14 with bar3 trimmed (reduce bar_mixed share) + dd to cadence band.
    Goal: bar_mixed 22-24%, all balanced."""
    R1 = {"cherry": 0.045, "1bar": 0.200, "2bar": 0.165, "3bar": 0.080,
          "high7": 0.075, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.062,
          "high7": 0.060, "doublediamond": 0.027, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.048,
          "high7": 0.050, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C36_classic_iconic():
    """C36: classic IGT 7-bar iconic shape. cherry 4.5/4/3, bar1 19/16/13,
    bar2 16/13/10, bar3 8/6/5 (lower for less bar_mixed), h7 6/5/4,
    dd 2.8/2.6/2.2."""
    R1 = {"cherry": 0.045, "1bar": 0.190, "2bar": 0.160, "3bar": 0.080,
          "high7": 0.060, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.040, "1bar": 0.160, "2bar": 0.130, "3bar": 0.060,
          "high7": 0.050, "doublediamond": 0.026, "jackpot": 0.004}
    R3 = {"cherry": 0.030, "1bar": 0.130, "2bar": 0.100, "3bar": 0.050,
          "high7": 0.040, "doublediamond": 0.022, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C37_C14_cad_into_band():
    """C37: C14 with dd just barely reduced — keep RTP in band but cadence into [50k, 100k].
    C14 cadence 1/44k; dd → 0.029/0.029/0.024 gives cube 2.02e-5 = 1/49.6k (close to floor).
    Slightly less, dd 0.028/0.028/0.024 gives cube 1.88e-5 = 1/53k. Try."""
    R1 = {"cherry": 0.040, "1bar": 0.200, "2bar": 0.166, "3bar": 0.105,
          "high7": 0.070, "doublediamond": 0.028, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.075,
          "high7": 0.055, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.045, "doublediamond": 0.024, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C38_C14_rtp_target_95():
    """C38: C14 with RTP target 95. dd 0.029/0.028/0.024, slight bar1 lift R1
    to compensate for cadence-adjusted dd."""
    R1 = {"cherry": 0.040, "1bar": 0.202, "2bar": 0.165, "3bar": 0.103,
          "high7": 0.072, "doublediamond": 0.029, "jackpot": 0.004}
    R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.073,
          "high7": 0.057, "doublediamond": 0.028, "jackpot": 0.004}
    R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
          "high7": 0.047, "doublediamond": 0.024, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


def C39_C14_v3():
    """C39: C14 base. dd at 0.029/0.029/0.023 (cube 1.94e-5 = 1/51.5k IN band).
    Slight cherry lift for cherry3."""
    R1 = {"cherry": 0.045, "1bar": 0.197, "2bar": 0.162, "3bar": 0.100,
          "high7": 0.070, "doublediamond": 0.029, "jackpot": 0.004}
    R2 = {"cherry": 0.038, "1bar": 0.163, "2bar": 0.133, "3bar": 0.073,
          "high7": 0.055, "doublediamond": 0.029, "jackpot": 0.004}
    R3 = {"cherry": 0.028, "1bar": 0.135, "2bar": 0.108, "3bar": 0.055,
          "high7": 0.045, "doublediamond": 0.023, "jackpot": 0.003,
          "topdollar": 0.0113}
    return make_marginals(R1, R2, R3)


CANDIDATES = [
    ("C1_classic_balanced", C1_classic_balanced),
    ("C2_low_cherry", C2_low_cherry),
    ("C3_high_cherry_low_h7", C3_high_cherry_low_h7),
    ("C4_bar_dominant_classic", C4_bar_dominant_classic),
    ("C5_high_h7_balanced", C5_high_h7_balanced),
    ("C6_RWB_proportions", C6_RWB_proportions),
    ("C7_double_diamond_style", C7_double_diamond_style),
    ("C8_symmetric", C8_symmetric),
    ("C9_stronger_asymmetry", C9_stronger_asymmetry),
    ("C10_low_RTP_floor_aim", C10_low_RTP_floor_aim),
    ("C11_cherry_heavy_hit", C11_cherry_heavy_hit),
    ("C12_balanced_no_dominant", C12_balanced_no_dominant),
    ("C13_high7_classic_seven", C13_high7_classic_seven),
    ("C14_C5_refined", C14_C5_refined),
    ("C15_C13_refined", C15_C13_refined),
    ("C16_balanced_target", C16_balanced_target),
    ("C17_seven_heavy_lower_bars", C17_seven_heavy_lower_bars),
    ("C18_C12_refined", C18_C12_refined),
    ("C19_C14_fix_cherry3_cadence", C19_C14_fix_cherry3_cadence),
    ("C20_C14_seven_anchor", C20_C14_seven_anchor),
    ("C21_lift_dd_for_cadence", C21_lift_dd_for_cadence),
    ("C22_balanced_v2", C22_balanced_v2),
    ("C23_C20_rtp_trim", C23_C20_rtp_trim),
    ("C24_balanced_seven_cherry", C24_balanced_seven_cherry),
    ("C25_top_h7_classic", C25_top_h7_classic),
    ("C26_C20_clean", C26_C20_clean),
    ("C27_recommended", C27_recommended),
    ("C28_recommended_v2", C28_recommended_v2),
    ("C29_lower_h7", C29_lower_h7),
    ("C30_minimal_diamond_balanced", C30_minimal_diamond_balanced),
    ("C31_C14_cadence_fix", C31_C14_cadence_fix),
    ("C32_C14_cherry_lift", C32_C14_cherry_lift),
    ("C33_anchor_classic", C33_anchor_classic),
    ("C34_C20_no_dominance", C34_C20_no_dominance),
    ("C35_C14_bar3_trim", C35_C14_bar3_trim),
    ("C36_classic_iconic", C36_classic_iconic),
    ("C37_C14_cad_into_band", C37_C14_cad_into_band),
    ("C38_C14_rtp_target_95", C38_C14_rtp_target_95),
    ("C39_C14_v3", C39_C14_v3),
]


def summary_row(name, r):
    fs = r["family_shares"]
    n_fail = sum(1 for _, _, st, _ in check_hardlines(r) if st == "FAIL")
    max_fam = max(fs.values()) if fs else 0
    min_fam_paid = min(fs.get(f, 0) for f in ("bar1", "bar2", "bar3", "high7", "cherry1", "bar_mixed"))
    return (name, n_fail, r["total_rtp"], r["hit_session"], r["r1_blank"],
            max_fam, min_fam_paid, r["wild_cadence"], r["base_rtp"],
            r["feature_rtp"])


def detailed_pay_report(name, r):
    """Detailed per-pay-id breakdown for selected candidate."""
    print(f"\n========== DETAILED PAY REPORT: {name} ==========")
    print(f"\nPer-pay-id (base game):")
    print(f"{'pay_id':>6} {'family':<14} {'mult':>4} {'hit%':>10} {'1 in N':>10} {'RTP pp':>8}")
    PAY_INFO = {
        "9":  ("cherry1", "1×"),
        "71": ("cherry2", "5×"),
        "4":  ("cherry3", "15×"),
        "1":  ("wild_pure", "200×"),
        "2":  ("high7_wild", "30×*"),
        "21": ("high7_pure", "30×"),
        "3":  ("bar3", "20×*"),
        "5":  ("bar2", "10×*"),
        "7":  ("bar1", "5×*"),
        "8":  ("bar_mixed", "2×*"),
        "666": ("topdollar_trig", "trig"),
    }
    pay_hits = r["pay_hits"]
    pay_rtp = r["pay_rtp"]
    for pid in ("9", "71", "4", "1", "21", "2", "3", "5", "7", "8"):
        fam, mult = PAY_INFO.get(pid, (pid, "?"))
        p = pay_hits.get(pid, 0)
        one_in = 1.0 / p if p > 0 else float("inf")
        rtp = pay_rtp.get(pid, 0) * 100
        print(f"{pid:>6} {fam:<14} {mult:>4} {p*100:>10.4f}% {one_in:>10.0f} {rtp:>8.3f}")

    print(f"\nFamily share-of-base (target: each 1-25%, none >28%):")
    for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                "bar_mixed", "high7", "wild_pure"):
        sh = r["family_shares"].get(fam, 0)
        if fam == "high7":
            pp = r["high7_combined_pp"]
        else:
            pp = r["family_pp"].get(fam, 0)
        flag = " *DOMINANT*" if sh > 28 else " (SLIM)" if sh < 1 else ""
        print(f"  {fam:<12}: {sh:>6.2f}%  {pp:>6.2f}pp{flag}")

    print(f"\nBar hierarchy (P(bar1_pure)>P(bar2_pure)>P(bar3_pure)):")
    p_b1 = pay_hits.get("7", 0)
    p_b2 = pay_hits.get("5", 0)
    p_b3 = pay_hits.get("3", 0)
    print(f"  bar1: P={p_b1*100:.4f}%")
    print(f"  bar2: P={p_b2*100:.4f}%")
    print(f"  bar3: P={p_b3*100:.4f}%")
    print(f"  Hierarchy: {'OK (bar1>bar2>bar3)' if p_b1 > p_b2 > p_b3 else 'INVERTED'}")

    print(f"\nCherry visibility:")
    cherry_marg = [r["margs"][i].get("cherry", 0) * 100 for i in range(3)]
    print(f"  R1 cherry marginal: {cherry_marg[0]:.2f}%")
    print(f"  R2 cherry marginal: {cherry_marg[1]:.2f}%")
    print(f"  R3 cherry marginal: {cherry_marg[2]:.2f}%")
    print(f"  cherry-1 hit: {pay_hits.get('9', 0)*100:.4f}%")
    print(f"  cherry-2 hit: {pay_hits.get('71', 0)*100:.4f}%")
    print(f"  cherry-3 hit: {pay_hits.get('4', 0)*100:.4f}%")

    p_wild = pay_hits.get("1", 0)
    cad = 1.0 / p_wild if p_wild > 0 else float("inf")
    print(f"\nwild_pure cadence: 1 in {cad:.0f} (band [1/50k, 1/100k])")
    print(f"  In band: {'YES' if 50000 <= cad <= 100000 else 'NO'}")

    print(f"\nPer-reel marginals:")
    for i, m in enumerate(r["margs"]):
        print(f"  R{i+1}:")
        for sym, mv in sorted(m.items(), key=lambda x: -x[1]):
            print(f"    {sym:<14}: {mv*100:>6.2f}%")

    # PWDF post-mechanism B
    pwdf, _ = pwdf_table(r["margs"], STRIPS)
    print(f"\nPost-mechanism-B PWDF table (any-reel window visibility, %):")
    print(f"  {'symbol':<16} {'R1':>6} {'R2':>6} {'R3':>6} {'MAX':>6}")
    for sym, row in pwdf.items():
        mx = max(row)
        print(f"  {sym:<16} {row[0]:>6.2f} {row[1]:>6.2f} {row[2]:>6.2f} {mx:>6.2f}")


def main():
    print("=" * 80)
    print("M15 v14 — Archetype-first redesign (no bucket bands)")
    print("=" * 80)

    results = {}
    print("\n--- Summary table ---")
    print(f"{'cand':<28} {'fail':>4} {'rtp':>7} {'hit':>6} {'R1b':>6} "
          f"{'maxFam%':>7} {'minPaid%':>8} {'cad':>10} {'base':>6} {'feat':>6}")
    for name, fn in CANDIDATES:
        try:
            margs = fn()
            r = evaluate(margs)
            results[name] = r
            row = summary_row(name, r)
            print(f"{row[0]:<28} {row[1]:>4} {row[2]:>7.3f} {row[3]:>6.2f} "
                  f"{row[4]:>6.2f} {row[5]:>7.2f} {row[6]:>8.2f} {row[7]:>10.0f} "
                  f"{row[8]:>6.2f} {row[9]:>6.2f}")
        except Exception as e:
            print(f"  {name}: ERROR {e}")

    print()
    print("--- Detailed reports ---")
    for name in results:
        report(name, results[name], verbose=True)

    # Choose top candidates by archetypal balance
    print("\n" + "=" * 80)
    print("Selection summary")
    print("=" * 80)
    qualified = []
    for name, r in results.items():
        checks = check_hardlines(r)
        n_fail = sum(1 for _, _, st, _ in checks if st == "FAIL")
        if n_fail == 0:
            fs = r["family_shares"]
            max_fam = max(fs.values()) if fs else 0
            min_paid = min(fs.get(f, 0) for f in ("bar1", "bar2", "bar3", "high7", "cherry1", "bar_mixed"))
            cadence_ok = 50000 <= r["wild_cadence"] <= 100000
            # rank: lower max_fam = less dominance; higher min_paid = better balance
            score = -max_fam + min_paid + (5 if cadence_ok else 0)
            qualified.append((score, name, max_fam, min_paid, r))
    qualified.sort(reverse=True)
    print(f"{'rank':>4} {'score':>7} {'cand':<28} {'maxFam':>7} {'minPaid':>8}")
    for i, (score, name, mf, mp, r) in enumerate(qualified):
        print(f"{i+1:>4} {score:>7.2f} {name:<28} {mf:>7.2f} {mp:>8.2f}")

    # Detailed inspection of the top candidate (selection target)
    if qualified:
        winner_name = qualified[0][1]
        detailed_pay_report(winner_name, results[winner_name])

    # Also detailed for finalists
    finalists = ["C14_C5_refined", "C38_C14_rtp_target_95",
                 "C37_C14_cad_into_band", "C31_C14_cadence_fix"]
    for name in finalists:
        if name in results:
            detailed_pay_report(name, results[name])

    return results, qualified


if __name__ == "__main__":
    main()
