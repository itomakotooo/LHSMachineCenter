"""M15 v14d Mode 5 redesign — fix "multiplier shift higher" intent.

Iteration 5 (v14d): Mode 5 only. Mode 1 (C38_C14), Mode 7 (M7_F110), Mode 2
(M2_LC) all shipped. v14c M5_LC_plus was REJECTED because its base ≥30× mult
share (35.15%) went LOWER than M2_LC's (36.17%) — used h7 cut 8% as the
easy RTP-balance lever, which undid the user-stated "向高 shift" intent.

User direct (2026-05-12):
    "mode5 就是在 mode2 基础上，把奖项倍率继续向高倍率移动。但同样屏蔽千倍以上的奖。"

Target: base ≥30× mult share ≥ 40% (vs M2_LC 36.17%, target ≥+4pp shift).

Approach priority (CORRECTED from v14c):
  (i)  KEEP h7 marginal ≥ M2_LC's h7 (R1≥12.17%, R2≥12.25%, R3≥12.22%).
       DO NOT cut h7. h7 anchors 30/60/120× pays.
  (ii) LIFT dd (wild) marginal vs M2_LC. dd lift cubically boosts:
       - wild_pure (3 dd) = 200× → ge200_lt500
       - bar+2wild = 20/40/80× → ge20_lt50 / ge50_lt100
       - h7+1wild = 60× → ge50_lt100
       - h7+2wild = 120× → ge100_lt200
       All ≥30× mult.
  (iii) Bar marginals proportional to M2_LC or slight lift (preserve §1).
  (iv) Cherry proportional to M2_LC (cherry-1 1× / cherry-2 5× are LOW mults).
  (v)  Trigger m5 ≥ m2 (3.30%). Can be slightly higher per LUCKY-MONO floor.
  (vi) Base RTP target ~98-105pp (user §d 不矫枉过正 — don't overpush).
  (vii) Total RTP target ~500pp in [490, 510]. Margin ≥2pp.

Constraints:
  - feature_params byte-equal v9 (locked).
  - Paytable byte-equal.
  - Strip layout unchanged.
  - Jackpot per-reel ≤ 0.6%.
  - P(R≥1000)/spin ≤ 1e-5.
  - All 13 cross-mode invariants pass.
  - DO NOT cut h7 below M2_LC level.
  - m5 hit ≥ m2 hit (with safety margin to survive integer rounding).
  - m5 trigger ≥ m2 trigger.
  - R1 blank ≥ R3 blank (lucky carve preserved).
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

_M15 = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15 / "spec.json"
STRIPS_PATH = _M15 / "reel_strips.json"
W_M1 = _M15 / "weights" / "mode_1" / "weights.json"
W_M2 = _M15 / "weights" / "mode_2" / "weights.json"
W_M5 = _M15 / "weights" / "mode_5" / "weights.json"
W_M7 = _M15 / "weights" / "mode_7" / "weights.json"

engine, _spec = load_engine(SPEC_PATH, W_M1, strips_path=STRIPS_PATH)
EV = engine.evaluator

# Feature params per mode (LOCKED byte-equal v9).
FP_BY_MODE = {
    1: json.loads(W_M1.read_text(encoding="utf-8"))["feature_params"],
    2: json.loads(W_M2.read_text(encoding="utf-8"))["feature_params"],
    5: json.loads(W_M5.read_text(encoding="utf-8"))["feature_params"],
    7: json.loads(W_M7.read_text(encoding="utf-8"))["feature_params"],
}


def feature_stats(fp):
    dist = _round_payout_distribution(
        tuple(fp["x_count_weights"]),
        tuple(fp["y_count_weights"]),
        tuple(fp["x_value_weights"]),
        tuple(fp["y_value_weights"]),
    )
    accept_thr = fp["accept_threshold"]
    p_accept = sum(p for r, p in dist if r >= accept_thr)
    if p_accept == 0:
        return {"ev": 0.0, "p_r_ge_200": 0.0, "p_r_ge_1000": 0.0,
                "p_accept": 0.0, "A": 0.0, "U": 0.0, "dist": dist}
    A = sum(r * p for r, p in dist if r >= accept_thr) / p_accept
    U = sum(r * p for r, p in dist)
    max_r = fp["max_rounds"]
    reject_streak = 1.0 - p_accept
    ev = 0.0
    for round_idx in range(1, max_r):
        ev += (reject_streak ** (round_idx - 1)) * p_accept * A
    ev += (reject_streak ** (max_r - 1)) * U
    p_r_ge_200 = sum(p for r, p in dist if r >= 200)
    p_r_ge_1000 = sum(p for r, p in dist if r >= 1000)
    return {"ev": ev, "p_r_ge_200": p_r_ge_200, "p_r_ge_1000": p_r_ge_1000,
            "p_accept": p_accept, "A": A, "U": U, "dist": dist}


FEAT = {m: feature_stats(fp) for m, fp in FP_BY_MODE.items()}

PAY_FAM = {"9": "cherry1", "71": "cherry2", "4": "cherry3", "1": "wild_pure",
           "2": "high7_wild", "21": "high7_pure", "3": "bar3", "5": "bar2",
           "7": "bar1", "8": "bar_mixed"}

# Per-pay multipliers from spec.json
PAY_MULTIPLIER = {"9": 1, "71": 5, "4": 15, "1": 200, "2": 30, "21": 30,
                  "3": 20, "5": 10, "7": 5, "8": 2}


def normalize(m):
    out = dict(m)
    nb = sum(v for k, v in out.items() if k != "blank")
    out["blank"] = max(0.0, 1.0 - nb)
    return out


def evaluate(margs, mode):
    prof = analytic_profile_from_marginals(EV, margs)
    base = prof["rtp_pct"]
    hit = prof["hit_rate"]
    trig = margs[2].get("topdollar", 0.0)
    feat = FEAT[mode]
    feat_rtp = trig * feat["ev"] * 100.0
    tot = base + feat_rtp
    fam_pp = defaultdict(float)
    for pid, rtp in prof["pay_rtp"].items():
        fam = PAY_FAM.get(pid)
        if fam is None:
            continue
        fam_pp[fam] += rtp * 100.0
    high7_combined = fam_pp.get("high7_wild", 0) + fam_pp.get("high7_pure", 0)
    fam_share = {}
    if base > 0:
        for fam in ("cherry1", "cherry2", "cherry3", "bar1", "bar2", "bar3",
                    "bar_mixed", "wild_pure"):
            fam_share[fam] = fam_pp.get(fam, 0) / base * 100.0
        fam_share["high7"] = high7_combined / base * 100.0
    p_wild = prof["pay_hits"].get("1", 0)
    return {
        "mode": mode, "total_rtp_pct": tot, "base_rtp_pct": base,
        "feature_rtp_pct": feat_rtp,
        "hit_session_pct": (hit + trig) * 100,
        "base_hit_pct": hit * 100,
        "trigger_pct": trig * 100, "trigger": trig,
        "r1_blank_pct": margs[0]["blank"] * 100,
        "r2_blank_pct": margs[1]["blank"] * 100,
        "r3_blank_pct": margs[2]["blank"] * 100,
        "pay_hits": prof["pay_hits"], "pay_rtp": prof["pay_rtp"],
        "family_pp": dict(fam_pp), "family_share_pct": fam_share,
        "high7_combined_pp": high7_combined,
        "wild_cad": 1.0 / p_wild if p_wild > 0 else float("inf"),
        "p_r_ge_1000_spin": trig * feat["p_r_ge_1000"],
        "p_r_ge_200_spin": trig * feat["p_r_ge_200"],
        "cv": prof["cv"], "margs": margs,
    }


def base_mult_tier_decomp_from_combos(margs):
    """Decompose base RTP by FINAL combo multiplier (post-wild-boost).

    Two views:
    - "combo_pp": True per-combo mult-bucketed RTP. Captures wild-boost
      reality (bar3+1wild=40× → ge30 bucket).
    - "payid_pp": Critique-X style. ALL pay_id RTP goes in one tier based
      on the pay_id's headline mult (pay_id 2 = 30×, pay_id 3 = 20×, etc.).
      Both are useful — combo_pp is the player-experience truth;
      payid_pp matches the design intent / X's review.
    """
    import itertools

    symbols_per_reel = [list(m.keys()) for m in margs]
    # combo_pp uses bucket per FINAL multiplier
    combo_tier_pp = {
        "1x_le1": 0.0, "ge2_lt5": 0.0, "ge5_lt10": 0.0, "ge10_lt20": 0.0,
        "ge20_lt30": 0.0, "ge30_lt50": 0.0, "ge50_lt100": 0.0,
        "ge100_lt200": 0.0, "ge200_lt500": 0.0, "ge500": 0.0,
    }
    # payid-keyed RTP (pp)
    pid_rtp_pp = defaultdict(float)
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

    base_pp = sum(combo_tier_pp.values())
    # ≥30× sum based on combo final mult
    ge_30_pp = (combo_tier_pp["ge30_lt50"] + combo_tier_pp["ge50_lt100"]
                + combo_tier_pp["ge100_lt200"] + combo_tier_pp["ge200_lt500"]
                + combo_tier_pp["ge500"])
    ge_30_share = ge_30_pp / base_pp * 100.0 if base_pp > 0 else 0.0

    # Critique-X style: pay_id-anchored buckets.
    # Per X's decomp Section J:
    # - 1×: pay 9 (cherry1)
    # - <15×: pay 71 (cherry2 5×) + pay 8 (bar_mixed 2/4×) + pay 7 (bar1 5/10/20×)
    # - 15×: pay 4 (cherry3)
    # - 30×: pay 21 (h7_pure 30×)
    # - 40-120×: pay 2 (h7+wild 30/60/120) + pay 3 (bar3 20/40/80) + pay 5 (bar2 10/20/40)
    # - 200×: pay 1 (wild_pure 200×)
    payid_tier_pp = {
        "1x": pid_rtp_pp.get("9", 0.0),
        "lt15": (pid_rtp_pp.get("71", 0.0) + pid_rtp_pp.get("8", 0.0)
                 + pid_rtp_pp.get("7", 0.0)),
        "15": pid_rtp_pp.get("4", 0.0),
        "30": pid_rtp_pp.get("21", 0.0),
        "40_120": (pid_rtp_pp.get("2", 0.0) + pid_rtp_pp.get("3", 0.0)
                   + pid_rtp_pp.get("5", 0.0)),
        "200": pid_rtp_pp.get("1", 0.0),
    }
    payid_ge30_pp = (payid_tier_pp["30"] + payid_tier_pp["40_120"]
                     + payid_tier_pp["200"])
    payid_ge30_share = payid_ge30_pp / base_pp * 100.0 if base_pp > 0 else 0.0

    return {
        "tier_pp": combo_tier_pp,
        "payid_tier_pp": payid_tier_pp,
        "pid_rtp_pp": dict(pid_rtp_pp),
        "base_pp": base_pp,
        "ge_30_pp": ge_30_pp,
        "ge_30_share_pct": ge_30_share,
        "payid_ge_30_pp": payid_ge30_pp,
        "payid_ge_30_share_pct": payid_ge30_share,
    }


def base_mult_tier_decomp(res):
    """Decompose base RTP by max-pay multiplier tier.
    Note: pay_id 8 (bar_mixed) is 2x or 4x (4x when one is wild).
    pay_id 7/5/3 (bar) is 5x/10x/20x base, 2x boost when 1 wild substitutes.
    pay_id 2 (h7+wild) is 30x base; 60x w/ 1 wild; 120x w/ 2 wild.
    pay_id 21 (h7 pure) 30x.
    pay_id 1 (wild_pure 3dd) 200x.

    For this analytic decomposition we use the FINAL multiplier each pay_id
    actually pays (from analytic_rtp). pay_id 2 is the wild-boosted variant
    so its average pay > 30; pay_id 8 average pay (2/4 mixed) > 2.

    For "≥30× share" definition we count pay_ids whose nominal MAX multiplier
    (or pure-line multiplier) is ≥30. Critique X used pay_id 2/3/21/1 as ≥30×.
    Match that approach.

    Buckets follow critique X's table (1-5, 5-15, 20-50, 50-100, 100-200, 200+).

    Since RTP per pay_id from analytic includes all wild boost variants:
    - pay_id 9 (cherry1 1x) → tier "1×"
    - pay_id 71 (cherry2 5x) → tier "5×"
    - pay_id 4 (cherry3 15x) → tier "15×"
    - pay_id 8 (bar_mixed 2/4x) → tier "2-5×" (low)
    - pay_id 7 (bar1 5/10/20x) → tier "5-20×"
    - pay_id 5 (bar2 10/20/40x) → tier "10-40×"
    - pay_id 3 (bar3 20/40/80x) → tier "20-80×"
    - pay_id 2 (h7 wild 30/60/120x) → tier "30-120×"
    - pay_id 21 (h7 pure 30x) → tier "30×"
    - pay_id 1 (wild_pure 200x) → tier "200×"
    """
    # Critique X bucket scheme from doc:
    # 1× (cherry1) / <15× (bar_mixed, cherry2 5x) / 15× (cherry3) /
    # 30× (h7_pure + h7+blank line) / 40-120× (bar/h7 wild) / 200× (wild_pure)
    pay_rtp = res["pay_rtp"]
    base_pp = res["base_rtp_pct"]

    # We want a tier decomp that lets us count "≥30×" share.
    # Use nominal pure-line multiplier as the family tier marker, but for the
    # wild-substituted pay_ids (3, 5, 7, 2, 8) the RTP includes boosted variants.
    # To approximate "≥30× share" we apportion pay_id RTP by sub-component.
    # The simplest faithful version: count pay_ids whose nominal pure mult ≥30
    # AS LOW-BOUND ≥30 share, then add wild-boosted high-mult contributions
    # from pays 3 (3-bar 20×; boosted to 40/80×) and pays 5 (bar2 10/20/40×).

    # For matching critique X's count (which simply used pay_id rtp buckets
    # by family-anchor mult), use:
    # ≥30× = wild_pure (200×) + high7_wild_combined (30/60/120 avg) +
    #        high7_pure (30) + part of bar3 (its 40/80 wild-boost slice)

    # Simpler robust approach: report
    #   tier_1x = pay 9 RTP only
    #   tier_lt15 = pay 8 + pay 71 RTP  (2/4× bar_mixed + 5× cherry2)
    #   tier_15 = pay 4 RTP (cherry3 15×)
    #   tier_30 = pay 21 RTP (h7 pure 30×)
    #   tier_40_120 = pay 2 RTP (h7+wild 30-120×, dominated by 60×) +
    #                 pay 3 RTP (bar3 20/40/80×) + pay 5 RTP (bar2 10/20/40×) +
    #                 pay 7 RTP (bar1 5/10/20×)
    #   tier_200 = pay 1 RTP (wild_pure 200×)
    # ≥30 share = (tier_30 + tier_40_120 wild slices + tier_200) / base
    #
    # But critique X showed the FULL bar pay_id RTP in the 40-120× bucket.
    # That's because the bar pay_ids' average pay is in that range (mostly
    # boosted via wild). We'll match X's scheme:

    pp = lambda k: pay_rtp.get(k, 0.0) * 100.0

    tier = {
        "1x": pp("9"),                       # cherry1
        "lt15": pp("71") + pp("8"),          # cherry2 5×, bar_mixed 2/4×
        "15": pp("4"),                       # cherry3 15×
        "30": pp("21"),                      # h7_pure 30×
        "40_120": pp("2") + pp("3") + pp("5") + pp("7"),  # bar3, bar2, bar1, h7_wild
        "200": pp("1"),                      # wild_pure 200×
    }

    # ≥30× = 30 + 40-120 + 200
    ge_30_pp = tier["30"] + tier["40_120"] + tier["200"]
    ge_30_share = ge_30_pp / base_pp * 100.0 if base_pp > 0 else 0.0

    # Also compute alternative critique-x scheme:
    # 1-5× / 5-15× / 20-50× / 50-100× / 100-200× / 200×+
    # Per spec task: these tiers refer to FINAL multipliers post-wild-boost.
    # Since analytic_rtp aggregates all variants in pay_rtp[pid], we
    # decompose using the analytic per-variant probability mass.
    # That requires deeper engine introspection. Approximate by using
    # pay_id anchor mult (pure-line, no wild) and accept the error margin.
    # For ≥30 share we mostly care about pay_id 1 (200×), pay_id 2 (30×+ all
    # variants), pay_id 21 (30×), and bar3 partial.

    # Improved tier scheme using nominal pure mults + bar wild-boost share:
    # We'll compute a "weighted high-mult share" by also splitting bar3 / bar2
    # wild-boost contributions.

    return {
        "tier_1x_pp": tier["1x"],
        "tier_lt15_pp": tier["lt15"],
        "tier_15_pp": tier["15"],
        "tier_30_pp": tier["30"],
        "tier_40_120_pp": tier["40_120"],
        "tier_200_pp": tier["200"],
        "ge_30_pp": ge_30_pp,
        "ge_30_share_pct": ge_30_share,
        "base_pp": base_pp,
    }


# =============================================================================
# Baseline references
# =============================================================================

# Mode 1 v14 C38_C14 shipped marginals
M1_MARGINALS = [
    {"blank": 0.3852, "cherry": 0.0400, "1bar": 0.2019, "2bar": 0.1648,
     "3bar": 0.1032, "high7": 0.0720, "doublediamond": 0.0290, "jackpot": 0.0040},
    {"blank": 0.5026, "cherry": 0.0350, "1bar": 0.1651, "2bar": 0.1353,
     "3bar": 0.0729, "high7": 0.0571, "doublediamond": 0.0280, "jackpot": 0.0040},
    {"blank": 0.5901, "cherry": 0.0250, "1bar": 0.1349, "2bar": 0.1099,
     "3bar": 0.0549, "high7": 0.0470, "doublediamond": 0.0240,
     "topdollar": 0.0112, "jackpot": 0.0030},
]
M1_RES = evaluate(M1_MARGINALS, 1)
M1_DECOMP = base_mult_tier_decomp_from_combos(M1_MARGINALS)

# Mode 2 M2_LC shipped marginals (from v14c)
M2_MARGINALS = [
    {"cherry": 0.06400, "1bar": 0.21805, "2bar": 0.17798, "3bar": 0.11146,
     "high7": 0.12168, "doublediamond": 0.02755, "jackpot": 0.004},
    {"cherry": 0.06300, "1bar": 0.23774, "2bar": 0.19483, "3bar": 0.10498,
     "high7": 0.12248, "doublediamond": 0.02520, "jackpot": 0.004},
    {"cherry": 0.05000, "1bar": 0.24282, "2bar": 0.19782, "3bar": 0.09882,
     "high7": 0.12220, "doublediamond": 0.02040, "topdollar": 0.03304,
     "jackpot": 0.003},
]
M2_MARGINALS = [normalize(m) for m in M2_MARGINALS]
M2_RES = evaluate(M2_MARGINALS, 2)
M2_DECOMP = base_mult_tier_decomp_from_combos(M2_MARGINALS)


# =============================================================================
# Mode 5 candidate generation
# =============================================================================

def make_m5_candidate(c_lift, b1_lift, b2_lift, b3_lift, h_lift_r, dd_lift_r, td_lift=1.0):
    """Build m5 marginals starting from M2_LC.

    c_lift: cherry multiplier (scalar)
    b1_lift / b2_lift / b3_lift: per-bar-family multiplier (allows non-uniform
            lift to shift mass from bar1 → bar2/bar3 (higher mults). Must preserve
            §1 hierarchy P(bar1) > P(bar2) > P(bar3) in final marginal.
    h_lift_r: (R1, R2, R3) high7 multiplier per reel
    dd_lift_r: (R1, R2, R3) doublediamond multiplier per reel
    td_lift: topdollar multiplier (m5 trigger = m2 trigger × td_lift)

    Constraint: h_lift_r values must be ≥ 1.0 (no h7 cut per task brief).
    """
    margs = []
    for r_idx, m in enumerate(M2_MARGINALS):
        new = {}
        h_lift = h_lift_r[r_idx]
        dd_lift = dd_lift_r[r_idx]
        assert h_lift >= 1.0 - 1e-9, f"h_lift[{r_idx}]={h_lift} cuts h7 (violates brief)"
        for sym, mg in m.items():
            if sym == "blank":
                continue
            elif sym == "doublediamond":
                new[sym] = mg * dd_lift
            elif sym == "topdollar":
                new[sym] = mg * td_lift
            elif sym == "cherry":
                new[sym] = mg * c_lift
            elif sym == "1bar":
                new[sym] = mg * b1_lift
            elif sym == "2bar":
                new[sym] = mg * b2_lift
            elif sym == "3bar":
                new[sym] = mg * b3_lift
            elif sym == "high7":
                new[sym] = mg * h_lift
            else:
                new[sym] = mg
        margs.append(normalize(new))
    return margs


# Critical invariant: m5 must have margin to m2 on hit AND trigger.
# Per critique v14c §3, m5 hit margin needs ≥0.05pp safe margin for integer
# rounding. Per critique trigger margin needs ≥1e-4 safe.

HIERARCHY_TIED_TOL = 0.001  # 0.10pp absolute per verify.py

def validate_m5(res, m2, m1, hit_margin_floor=0.0005, trig_margin_floor=1e-4):
    """Validate m5 vs all 13 cross-mode invariants + family-share + extras."""
    checks = []

    # 1. RTP target with margin (task brief vii: ~500pp ±, ≥2pp from edges → [492, 508])
    # NOTE: shipped v9 m5 was 508.83pp at boundary so being above 508 isn't fatal.
    # I'll use task user-target [491.5, 508.5] as soft target, [490, 510] as RED.
    rtp_ok = 491.5 <= res["total_rtp_pct"] <= 508.5
    checks.append(("[USER-RTP] m5 RTP in [491.5, 508.5]", rtp_ok,
                   f"{res['total_rtp_pct']:.3f}pp"))
    # Verify band [490, 510] per task — hard RED
    rtp_verify_ok = 490.0 <= res["total_rtp_pct"] <= 510.0
    checks.append(("[CROSS-RTP m5 band] [490, 510]", rtp_verify_ok,
                   f"{res['total_rtp_pct']:.3f}pp"))

    # 2. CROSS-RTP m5 > m2
    cross_rtp = res["total_rtp_pct"] > m2["total_rtp_pct"]
    checks.append(("[CROSS-RTP] m5 > m2", cross_rtp,
                   f"{res['total_rtp_pct']:.3f} > {m2['total_rtp_pct']:.3f}"))

    # 3. HIT band [0.30, 0.35]
    base_hit = res["base_hit_pct"] / 100
    hit_ok = 0.30 <= base_hit <= 0.35
    checks.append(("[HIT m5 band] [0.30, 0.35]", hit_ok, f"{base_hit:.4f}"))

    # 4. LUCKY-MONO m5 hit >= m2 hit  (with margin)
    m2_hit = m2["base_hit_pct"] / 100
    lucky_hit = base_hit >= m2_hit + hit_margin_floor
    checks.append((f"[LUCKY-MONO hit] m5 >= m2 + {hit_margin_floor*100:.2f}pp margin",
                   lucky_hit, f"{base_hit:.4f} vs {m2_hit:.4f} "
                              f"(diff {(base_hit-m2_hit)*100:+.3f}pp)"))

    # 5. LUCKY-MONO m5 trigger >= m2 trigger (with margin)
    lucky_trig = res["trigger"] >= m2["trigger"] + trig_margin_floor
    checks.append((f"[LUCKY-MONO trig] m5 >= m2 + {trig_margin_floor:.0e} margin",
                   lucky_trig,
                   f"{res['trigger']*100:.4f}% vs {m2['trigger']*100:.4f}% "
                   f"(diff {(res['trigger']-m2['trigger'])*100:+.4f}pp)"))

    # 6. TOP-JACKPOT-CADENCE m5/m2 >= 1.1
    pwild_m2 = m2["pay_hits"].get("1", 1e-12)
    pwild_m5 = res["pay_hits"].get("1", 0)
    cad_ratio = pwild_m5 / pwild_m2
    cad_ok = cad_ratio >= 1.1
    checks.append(("[TOP-JACKPOT-CADENCE m5/m2 >= 1.1]", cad_ok,
                   f"ratio={cad_ratio:.3f}"))

    # 7. Bar §1 hierarchy P(bar1)>P(bar2)>P(bar3) — with HIERARCHY_TIED_TOL
    # NOTE: verify.py treats m2/m5 bar hierarchy as INFO not RED (line 635).
    # For m5 design coherence with M2_LC anchor, I keep this check as RED but
    # match verify.py's tied tolerance (0.10pp absolute).
    b1 = res["pay_hits"].get("7", 0)
    b2 = res["pay_hits"].get("5", 0)
    b3 = res["pay_hits"].get("3", 0)
    bar_ok = (b1 >= b2 - HIERARCHY_TIED_TOL) and (b2 >= b3 - HIERARCHY_TIED_TOL)
    checks.append(("[BAR-HIERARCHY-§1] P(bar1)>=P(bar2)>=P(bar3) tied-tol 0.10pp", bar_ok,
                   f"b1={b1*100:.4f}% b2={b2*100:.4f}% b3={b3*100:.4f}%"))

    # 8. Cherry hierarchy
    c1 = res["pay_hits"].get("9", 0)
    c2 = res["pay_hits"].get("71", 0)
    c3 = res["pay_hits"].get("4", 0)
    c_ok = (c1 >= c2 - HIERARCHY_TIED_TOL) and (c2 >= c3 - HIERARCHY_TIED_TOL)
    checks.append(("[CHERRY-HIERARCHY] c1 >= c2 >= c3", c_ok,
                   f"c1={c1*100:.4f}% c2={c2*100:.4f}% c3={c3*100:.4f}%"))

    # 9. H7 hierarchy (h7_wild >= h7_pure within tied tol)
    h7w = res["pay_hits"].get("2", 0)
    h7p = res["pay_hits"].get("21", 0)
    h7_ok = h7w >= h7p - HIERARCHY_TIED_TOL
    checks.append(("[H7-HIERARCHY] h7_wild >= h7_pure - 0.10pp", h7_ok,
                   f"h7w={h7w*100:.4f}% h7p={h7p*100:.4f}% "
                   f"diff={(h7p-h7w)*100:+.4f}pp"))

    # 10. P(R>=1000)/spin <= 1e-5
    p_r1k_ok = res["p_r_ge_1000_spin"] <= 1e-5
    checks.append(("[1000+] P(R>=1000)/spin <= 1e-5", p_r1k_ok,
                   f"{res['p_r_ge_1000_spin']:.3e}"))

    # 11. Jackpot per-reel <= 0.6%
    jp_ok = all(m.get("jackpot", 0) <= 0.006 for m in res["margs"])
    checks.append(("[JACKPOT-VIS] all reels jp <= 0.6%", jp_ok, ""))

    # 12. Reel asymmetry per shipped v9 lucky carve-out
    r1r3_ok = res["r1_blank_pct"] >= res["r3_blank_pct"]
    checks.append(("[REEL-ASYM-LUCKY] R1 blank >= R3 blank", r1r3_ok,
                   f"R1={res['r1_blank_pct']:.2f} R3={res['r3_blank_pct']:.2f}"))

    # 13. TOP-JACKPOT-ESC P(R>=200)/spin m5 > m2
    esc_ok = res["p_r_ge_200_spin"] > m2["p_r_ge_200_spin"]
    checks.append(("[TOP-JACKPOT-ESC] P(R>=200)/spin m5 > m2", esc_ok,
                   f"{res['p_r_ge_200_spin']:.3e} > {m2['p_r_ge_200_spin']:.3e}"))

    # 14. h7 marginal not cut below M2_LC's
    h7_kept = all(res["margs"][r].get("high7", 0) >=
                  M2_MARGINALS[r].get("high7", 0) - 1e-6
                  for r in range(3))
    checks.append(("[H7-NOT-CUT] high7 marg ≥ M2_LC marg per reel", h7_kept,
                   f"R1: {res['margs'][0].get('high7',0)*100:.3f}≥"
                   f"{M2_MARGINALS[0].get('high7',0)*100:.3f}; "
                   f"R2: {res['margs'][1].get('high7',0)*100:.3f}≥"
                   f"{M2_MARGINALS[1].get('high7',0)*100:.3f}; "
                   f"R3: {res['margs'][2].get('high7',0)*100:.3f}≥"
                   f"{M2_MARGINALS[2].get('high7',0)*100:.3f}"))

    # 15. Family-share m5 sanity (m5 inherits m2 cap; bar3 [5,22] hard)
    fs = res["family_share_pct"]
    b3_sh_ok = 5.0 <= fs["bar3"] <= 22.0
    checks.append(("[FAM-SHARE b3 [5, 22]]", b3_sh_ok, f"{fs['bar3']:.2f}%"))
    # wild_pure soft cap to avoid breach in m5 specifically — m5 cap relaxed,
    # but keep noting share.
    wsh = fs["wild_pure"]
    checks.append((f"[FAM-SHARE wld informational]", True, f"{wsh:.3f}%"))

    return checks


# =============================================================================
# Search space
# =============================================================================

def sweep_candidates():
    """Generate candidates and rank by base ≥30× share + invariant passes."""
    results = []
    # Strategy:
    # h_lift_r must be ≥ 1.0 (do NOT cut h7).
    # dd_lift_r: explore range [1.0, 2.5] per reel.
    # b_lift: [0.95, 1.10] (slight tweaks).
    # c_lift: [0.95, 1.10] (slight tweaks).
    # td_lift: [1.0, 1.10] (m5 trigger ≥ m2 trigger).

    # Critical: lifting dd cubically lifts wild_pure (200×). Need to keep
    # P(R≥1000)/spin ≤ 1e-5 → constrains dd lift via wild_pure cadence.
    # Since base alone cannot pay 1000× (max=200× wild_pure), 1000+ comes
    # from feature only. P(R≥1000)/spin = trigger × P(R≥1000)/trigger.
    # Mode 5 P(R≥1000)/trigger from feature_params is 3.33e-6 (per critique).
    # So P(R≥1000)/spin = 0.033 × 3.33e-6 ≈ 1.1e-7 << 1e-5. SAFE regardless.
    # P(R≥1000)/spin constraint NOT binding from dd lift.

    # Real constraints:
    # - Total RTP ∈ [491.5, 508.5] target
    # - h7 marginal ≥ M2_LC's (h_lift_r ≥ 1.0)
    # - Base hit ≥ m2 hit (33.85%) + 0.05pp margin
    # - Trigger ≥ m2 trigger (3.304%) + 1e-4 margin
    # - bar §1 hierarchy preserved
    # - R1 blank ≥ R3 blank
    # - Base ≥30× share ≥ 40% (key new target)

    # Approach:
    # 1) Lift dd substantially (cubically lifts wild_pure to 200× tier;
    #    quadratically lifts wild-bar/h7-wild paths to 30-120× tier).
    # 2) Slightly lift h7 (releases 30/60/120× anchor pays).
    # 3) Bars and cherry roughly equal to M2_LC (keep hit close).
    # 4) Total RTP balance via td or base RTP target.

    # Note: cherry1 is anywhere (1×) — lifting cherry hits hard on hit rate
    # but contributes LOW mult. To get hit margin while shifting high, we
    # can lift cherry SLIGHTLY (e.g., x1.01-1.05) for hit margin.

    # SWEEP grid. Key levers:
    # - dd lift cubically lifts wild_pure 200× → drives ≥30× share
    # - bar1 CUT (5/10/20× boosted; bar1 has low P so small hit impact;
    #            cutting bar1 makes RTP room WITHOUT killing hit much)
    # - cherry LIFT compensates hit (cherry-1 anywhere; 1pp marg lift → ~1pp hit lift)
    # - h7 LIFT (anchor for 30/60/120× — direct ≥30 RTP lift; locked NOT to cut per task)
    # - bar2/bar3 LIFT (10/20/40 and 20/40/80× — bridge to high mult)
    # - td_lift ≥ 1.005 ensures m5 trigger > m2 trigger (integer-rounding safety)
    c_lift_options = [1.00, 1.03, 1.05, 1.07, 1.10, 1.13]
    b1_lift_options = [0.75, 0.80, 0.83, 0.85, 0.88, 0.90, 0.92, 0.95]
    b2_lift_options = [1.00, 1.03, 1.05, 1.08, 1.10, 1.15]
    b3_lift_options = [1.00, 1.05, 1.10, 1.15, 1.20]
    h_uniform_options = [1.00, 1.03, 1.05, 1.08, 1.10]
    dd_uniform_options = [1.03, 1.05, 1.08, 1.10, 1.13, 1.15]
    td_lift_options = [1.005]

    # Limit combinations to manageable size with smart pre-filters.
    n_tested = 0
    n_pass = 0

    for c_lift in c_lift_options:
        for b1_lift in b1_lift_options:
            for b2_lift in b2_lift_options:
                for b3_lift in b3_lift_options:
                    for h_uniform in h_uniform_options:
                        h_r1 = h_r2 = h_r3 = h_uniform
                        for dd_uniform in dd_uniform_options:
                            dd_r1 = dd_r2 = dd_r3 = dd_uniform
                            for td_lift in td_lift_options:
                                n_tested += 1
                                m5 = make_m5_candidate(
                                    c_lift, b1_lift, b2_lift, b3_lift,
                                    (h_r1, h_r2, h_r3),
                                    (dd_r1, dd_r2, dd_r3),
                                    td_lift,
                                )
                                if any(mg.get("blank", 0) < 0.05 for mg in m5):
                                    continue
                                res = evaluate(m5, 5)
                                if not (488.0 <= res["total_rtp_pct"] <= 510.0):
                                    continue
                                decomp = base_mult_tier_decomp_from_combos(m5)
                                ge30_share = decomp["payid_ge_30_share_pct"]

                                cks = validate_m5(res, M2_RES, M1_RES)
                                n_pass_inv = sum(1 for _, ok, _ in cks if ok)
                                n_check = len(cks)
                                all_pass = (n_pass_inv == n_check)

                                results.append({
                                    "c_lift": c_lift,
                                    "b1_lift": b1_lift,
                                    "b2_lift": b2_lift,
                                    "b3_lift": b3_lift,
                                    "h_r": (h_r1, h_r2, h_r3),
                                    "dd_r": (dd_r1, dd_r2, dd_r3),
                                    "td_lift": td_lift,
                                    "res": res,
                                    "decomp": decomp,
                                    "ge_30_share": ge30_share,
                                    "all_pass": all_pass,
                                    "n_pass_inv": n_pass_inv,
                                    "n_check": n_check,
                                })
                                if all_pass:
                                    n_pass += 1

    print(f"Tested {n_tested} candidates; {len(results)} after RTP/hit/trig filter; "
          f"{n_pass} pass ALL invariants")
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("M15 v14d Mode 5 redesign — fix 'multiplier shift higher' intent")
    print("=" * 80)

    print(f"\n--- Anchors ---")
    print(f"M1 base RTP = {M1_RES['base_rtp_pct']:.3f}pp, "
          f"hit = {M1_RES['base_hit_pct']:.3f}%, "
          f"trigger = {M1_RES['trigger_pct']:.4f}%")
    print(f"M1 base ≥30× share (combo): {M1_DECOMP['ge_30_share_pct']:.2f}%  "
          f"(payid-anchored: {M1_DECOMP['payid_ge_30_share_pct']:.2f}%)")
    print(f"M2_LC base RTP = {M2_RES['base_rtp_pct']:.3f}pp, "
          f"hit = {M2_RES['base_hit_pct']:.3f}%, "
          f"trigger = {M2_RES['trigger_pct']:.4f}%")
    print(f"M2_LC total RTP = {M2_RES['total_rtp_pct']:.3f}pp")
    print(f"M2_LC base ≥30× share (combo): {M2_DECOMP['ge_30_share_pct']:.2f}%  "
          f"(payid-anchored: {M2_DECOMP['payid_ge_30_share_pct']:.2f}%) "
          f"[task target ≥40% per X's payid-anchored convention]")
    print(f"M2_LC family pp: " + ", ".join(
        f"{k}={v:.2f}" for k, v in sorted(M2_RES['family_pp'].items())))

    print(f"\nFEATURE EV per mode: " + ", ".join(
        f"m{m}={FEAT[m]['ev']:.2f}" for m in (1, 2, 5, 7)))

    print(f"\nM5 feature EV = {FEAT[5]['ev']:.2f}x; with trigger 3.304% → "
          f"feature_rtp ~= {0.03304 * FEAT[5]['ev'] * 100:.2f}pp")

    print(f"\n--- Sweeping candidates ---")
    results = sweep_candidates()

    # Filter to all-pass
    passing = [r for r in results if r["all_pass"]]
    print(f"\n{len(passing)} candidates pass ALL invariants")

    if not passing:
        # Diagnostic - what invariants are failing?
        print("\nNo all-pass found. Best near-misses (filter: hit ≥ 33.85, "
              "trig ≥ 3.304):")
        diag = [r for r in results if r["res"]["total_rtp_pct"] >= 488 and
                r["res"]["total_rtp_pct"] <= 510 and
                r["res"]["base_hit_pct"] >= 33.85 and
                r["res"]["trigger"] >= 0.03304]
        diag.sort(key=lambda x: (-x["n_pass_inv"], -x["ge_30_share"]))
        for r in diag[:30]:
            # Show which inv failed
            cks = validate_m5(r["res"], M2_RES, M1_RES)
            fails = [label for label, ok, _ in cks if not ok]
            print(f"  c={r['c_lift']:.2f} b1={r['b1_lift']:.2f} b2={r['b2_lift']:.2f} "
                  f"b3={r['b3_lift']:.2f} h={r['h_r']} dd={r['dd_r']} "
                  f"td={r['td_lift']:.3f}: "
                  f"{r['n_pass_inv']}/{r['n_check']} pass, "
                  f"≥30share={r['ge_30_share']:.2f}%, "
                  f"RTP={r['res']['total_rtp_pct']:.2f}pp, "
                  f"hit={r['res']['base_hit_pct']:.2f}, "
                  f"trig={r['res']['trigger_pct']:.3f}, "
                  f"fail={fails[:3]}")

        # Plus: top by ≥30 share regardless of hit
        print("\nTop by ≥30 share (any hit):")
        diag2 = sorted(results, key=lambda x: -x["ge_30_share"])[:15]
        for r in diag2:
            cks = validate_m5(r["res"], M2_RES, M1_RES)
            fails = [label for label, ok, _ in cks if not ok]
            print(f"  c={r['c_lift']:.2f} b1={r['b1_lift']:.2f} b2={r['b2_lift']:.2f} "
                  f"b3={r['b3_lift']:.2f} h={r['h_r']} dd={r['dd_r']} "
                  f"td={r['td_lift']:.3f}: "
                  f"≥30share={r['ge_30_share']:.2f}%, "
                  f"RTP={r['res']['total_rtp_pct']:.2f}, "
                  f"hit={r['res']['base_hit_pct']:.2f}, "
                  f"trig={r['res']['trigger_pct']:.3f}, "
                  f"fail={fails[:3]}")
    else:
        # Rank passing candidates by base ≥30× share (priority metric)
        passing.sort(key=lambda r: -r["ge_30_share"])
        print(f"\nTop 10 by base ≥30× share:")
        for r in passing[:10]:
            print(f"  ≥30share={r['ge_30_share']:.2f}%  "
                  f"RTP={r['res']['total_rtp_pct']:.2f}pp  "
                  f"hit={r['res']['base_hit_pct']:.2f}%  "
                  f"trig={r['res']['trigger_pct']:.3f}%  "
                  f"wild_cad=1/{r['res']['wild_cad']:.0f}  "
                  f"c={r['c_lift']:.2f} b1={r['b1_lift']:.2f} b2={r['b2_lift']:.2f} "
                  f"b3={r['b3_lift']:.2f} h={r['h_r']} dd={r['dd_r']} td={r['td_lift']:.3f}")

        # Best candidate: max ≥30 share with safe margins
        # Prefer candidates with ≥30 share ≥ 40 AND RTP centered (496-506)
        best = None
        for r in passing:
            if r["ge_30_share"] >= 40.0 and 496.0 <= r["res"]["total_rtp_pct"] <= 506.0:
                best = r
                break
        if best is None:
            # Fall back: max ≥30 share
            best = passing[0]

        print(f"\n=== RECOMMENDED CANDIDATE ===")
        print(f"c_lift={best['c_lift']:.3f}  b1_lift={best['b1_lift']:.3f}  "
              f"b2_lift={best['b2_lift']:.3f}  b3_lift={best['b3_lift']:.3f}")
        print(f"h_lift_r={best['h_r']}  dd_lift_r={best['dd_r']}  td_lift={best['td_lift']:.3f}")
        print(f"\nKey metrics:")
        res = best["res"]
        decomp = best["decomp"]
        print(f"  Total RTP: {res['total_rtp_pct']:.3f}pp  "
              f"(target [491.5, 508.5])")
        print(f"  Base RTP: {res['base_rtp_pct']:.3f}pp")
        print(f"  Feature RTP: {res['feature_rtp_pct']:.3f}pp")
        print(f"  Base hit: {res['base_hit_pct']:.3f}%  (target ≥ M2 33.85% + 0.05pp margin)")
        print(f"  Trigger: {res['trigger_pct']:.4f}%  (≥ M2 3.304% + 1e-4 margin)")
        print(f"  Wild_pure cadence: 1/{res['wild_cad']:.0f}  "
              f"(m5/m2 ratio = {res['pay_hits'].get('1', 0) / M2_RES['pay_hits'].get('1', 1e-12):.3f})")
        print(f"  R1/R2/R3 blank: {res['r1_blank_pct']:.2f}/{res['r2_blank_pct']:.2f}/{res['r3_blank_pct']:.2f}")
        print(f"  P(R≥1000)/spin: {res['p_r_ge_1000_spin']:.3e}")
        print(f"  P(R≥200)/spin: {res['p_r_ge_200_spin']:.3e}")

        print(f"\nBase mult tier decomp (relative to M2_LC):")
        for tier in ("1x_le1", "ge2_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt30",
                     "ge30_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500", "ge500"):
            cur = decomp["tier_pp"].get(tier, 0.0)
            m2v = M2_DECOMP["tier_pp"].get(tier, 0.0)
            print(f"  {tier:14s}  {cur:6.3f}pp  (M2_LC {m2v:6.3f}, "
                  f"Δ={cur-m2v:+.3f}pp)")
        print(f"  ≥30× sum (combo bucketed by FINAL mult):"
              f" {decomp['ge_30_pp']:.3f}pp  (M2_LC {M2_DECOMP['ge_30_pp']:.3f}pp)")
        print(f"  ≥30× share (combo): {decomp['ge_30_share_pct']:.2f}%  "
              f"(M2_LC {M2_DECOMP['ge_30_share_pct']:.2f}%)  "
              f"Δ={decomp['ge_30_share_pct'] - M2_DECOMP['ge_30_share_pct']:+.2f}pp")
        print(f"  ≥30× share (payid-anchored, X's convention):"
              f" {decomp['payid_ge_30_share_pct']:.2f}%  "
              f"(M2_LC {M2_DECOMP['payid_ge_30_share_pct']:.2f}%)  "
              f"Δ={decomp['payid_ge_30_share_pct'] - M2_DECOMP['payid_ge_30_share_pct']:+.2f}pp  "
              f"[TASK TARGET ≥ 40%]")
        print(f"  ≥30× share: {decomp['ge_30_share_pct']:.2f}%  "
              f"(M2_LC {M2_DECOMP['ge_30_share_pct']:.2f}%)  "
              f"Δ={decomp['ge_30_share_pct'] - M2_DECOMP['ge_30_share_pct']:+.2f}pp")

        print(f"\nFamily share (% of base RTP):")
        for fam, sh in sorted(res["family_share_pct"].items(),
                              key=lambda kv: -kv[1]):
            m2_sh = M2_RES["family_share_pct"].get(fam, 0)
            print(f"  {fam:14s}  {sh:6.2f}%  (M2_LC {m2_sh:.2f}%, "
                  f"Δ={sh-m2_sh:+.2f}pp)")

        print(f"\nMarginal table (R1/R2/R3):")
        for sym in ["blank", "cherry", "1bar", "2bar", "3bar", "high7",
                    "doublediamond", "topdollar", "jackpot"]:
            v = [res["margs"][r].get(sym, 0) * 100 for r in range(3)]
            m2v = [M2_MARGINALS[r].get(sym, 0) * 100 for r in range(3)]
            print(f"  {sym:14s}  R1={v[0]:6.3f} (M2 {m2v[0]:.3f})  "
                  f"R2={v[1]:6.3f} (M2 {m2v[1]:.3f})  "
                  f"R3={v[2]:6.3f} (M2 {m2v[2]:.3f})")

        # Run invariants summary
        cks = validate_m5(res, M2_RES, M1_RES)
        print(f"\nInvariants check ({sum(1 for _, ok, _ in cks if ok)}/{len(cks)} PASS):")
        for label, ok, detail in cks:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}]  {label:60s}  {detail}")

        # Save recommended candidate
        out_path = _ROOT / "session_artifacts" / "M15" / "scripts" / \
                   "m15_v14d_mode5_candidate.json"
        save_data = {
            "candidate_name": "M5_HMV_plus",  # High-Mult-Visible plus
            "iteration": "v14d",
            "c_lift": best["c_lift"],
            "b1_lift": best["b1_lift"],
            "b2_lift": best["b2_lift"],
            "b3_lift": best["b3_lift"],
            "h_lift_r": best["h_r"],
            "dd_lift_r": best["dd_r"],
            "td_lift": best["td_lift"],
            "marginals": [res["margs"][r] for r in range(3)],
            "metrics": {
                "total_rtp_pct": res["total_rtp_pct"],
                "base_rtp_pct": res["base_rtp_pct"],
                "feature_rtp_pct": res["feature_rtp_pct"],
                "base_hit_pct": res["base_hit_pct"],
                "trigger_pct": res["trigger_pct"],
                "wild_cad": res["wild_cad"],
                "p_r_ge_1000_spin": res["p_r_ge_1000_spin"],
                "p_r_ge_200_spin": res["p_r_ge_200_spin"],
                "ge_30_share_pct": decomp["ge_30_share_pct"],
                "ge_30_pp": decomp["ge_30_pp"],
                "family_share_pct": res["family_share_pct"],
                "family_pp": res["family_pp"],
                "pay_hits": {k: v for k, v in res["pay_hits"].items()},
                "pay_rtp": {k: v for k, v in res["pay_rtp"].items()},
            },
        }
        out_path.write_text(json.dumps(save_data, indent=2, default=str), encoding="utf-8")
        print(f"\nSaved recommended candidate to: {out_path}")

        # Top 3 alternatives
        alt_top = passing[:5]
        print(f"\n=== TOP 5 BY ≥30× SHARE ===")
        for i, r in enumerate(alt_top):
            print(f"\nAlt {i+1}: ≥30share={r['ge_30_share']:.2f}%  "
                  f"RTP={r['res']['total_rtp_pct']:.2f}  "
                  f"hit={r['res']['base_hit_pct']:.2f}  "
                  f"trig={r['res']['trigger_pct']:.3f}  "
                  f"wild_cad=1/{r['res']['wild_cad']:.0f}")
            print(f"      c={r['c_lift']:.2f}  b1={r['b1_lift']:.2f}  "
                  f"b2={r['b2_lift']:.2f}  b3={r['b3_lift']:.2f}  "
                  f"h={r['h_r']}  dd={r['dd_r']}  td={r['td_lift']:.3f}")
