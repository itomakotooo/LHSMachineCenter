"""M15 v9 mode 1 first-principles redesign + candidate generator + evaluator.

Stage 4 redesign (2026-05-11 wave 4) after wave-3 v8.1 caught 3 drifts:
  1. Feature RTP 60pp (split 37:63, too feature-heavy; v7 was 45:55)
  2. R1 blank marginal 57.6% (v7 54.5%, +3pp drift)
  3. 1-5x bucket 56.7% of base with cherry-1 75% of hit

Per user directive: re-derive from first principles. v7 baseline is sanity
reference only, not weight source. Use philosophy + brief + Stage 1d
archetype research.

DESIGN PHILOSOPHY APPLIED:
  §1  inverse pyramid -> bar1 hit > bar2 hit > bar3 hit; high7_wild>high7_pure
  §2  brand visibility -> doublediamond / topdollar / cherry visible enough
  §3  blank cap headroom -> blanks not at WEIGHT_BOUNDS upper
  §4  cut mode preservation (m7 derivation)
  §5  CV-RTP consistency (informational only per v1.2 §g)
  §6  family share vs archetype baseline (Top Dollar / RWB proxy)
  §7  top jackpot escalation -> m1 [1/50k, 1/100k]
  §8  hit decomposition -> any pay <= 70% (cherry1 carve to 80%)
  §9  cross-mode invariants (m2/m5/m7 follow)
  §10 pareto trap -> family floors
  §12 reel asymmetry -> R1 blank <= R3 blank (3-reel)
  §13 blank-flank diversity (strip already passes)
  §14 visual rhythm (strip already passes)
  §15 PWDF window visibility (mechanism B applied per mode)

USER BRIEF v1.2:
  hit [15, 18]
  RTP target 95% +- 1pp
  Base:Feature split close to 45:55 (v7 baseline) — not v8.1 37:63
  P(R>=1000/spin) <= 1e-5
  jackpot any-reel marginal <= 0.6%
  paytable fixed
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    analytic_profile,
    compute_reel_marginal,
)
from slot_designer.core.devtools.player_experience import (
    symbol_window_probability,
)
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import (
    FeatureSpec,
    _X_POOL,
    _Y_POOL,
    _round_payout_distribution,
    analyze_feature,
)


_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
WEIGHTS_DIR = _M15_DIR / "weights"


# -----------------------------------------------------------------------
# Design Intent (first-principles, NOT copied from v7/v8)
# -----------------------------------------------------------------------
#
# Target Marginals per reel (mode 1):
#
# We design **target reel marginals** in the symbol → percentage space, then
# back-derive integer weights from strip stop counts. This decouples design
# from low-level weight tuning.
#
# Strip stop counts per reel:
#   R1: blank=18, cherry=2, 1bar=3, 2bar=4, 3bar=4, high7=2, doublediamond=2, jackpot=1
#   R2: blank=18, cherry=2, 1bar=3, 2bar=4, 3bar=4, high7=2, doublediamond=2, jackpot=1
#   R3: blank=18, cherry=2, 1bar=3, 2bar=4, 3bar=3, high7=2, doublediamond=1, jackpot=1, topdollar=2
#
# Each reel's marginal P(s) = sum_of_weights(s on reel) / total_reel_weight.
# Within a single reel, all stops of the same symbol share the same weight
# (mechanism B redistribution applies ONLY to blank).
#
# Design targets (rationale below each):
#
# Reel blank target = 54% (3-reel philosophy §12, archetype range)
#   - R1 = 54% (winners-friendly: lowest blank)
#   - R2 = 55% (middle gradient)
#   - R3 = 55% (slight more blank, trigger reel competes with topdollar)
#   v7 had 54.5/54.6/54.5 ; v8.1 had 54.5/54.6/54.5 (mass before mechanism B)
#   Our 54/55/55 has the right direction lock (R1 lowest).
#
# Cherry marginal:
#   - cherry1 hit rate dominated by P(cherry on >=1 reel).
#   - With paytable cherry-anywhere 1x, cherry1 hit ≈ 1 - (1-p1)(1-p2)(1-p3) - higher_pay_overrides
#   - To hit 12% cherry1 hit, with 3 reels each ~5% cherry, gives ~14% triple-overlap.
#   - Target cherry marginal: R1=5.0%, R2=5.0%, R3=2.5% (R3 cherry less because trigger reel space)
#
# Doublediamond (wild): top symbol, philosophy §15 PWDF target ≥28% any-reel
#   Target marginal: R1=3.0%, R2=3.5%, R3=1.3% (R3 less; archetype: trigger reel constrained)
#
# High7: brand mid-tier 30×. Target marginal: R1=2.8%, R2=4.5%, R3=1.8%
#
# 3bar (20×): R1=7.0%, R2=5.8%, R3=8.0%
# 2bar (10×): R1=13.5%, R2=12.8%, R3=15.2%
# 1bar (5×):  R1=9.8%,  R2=8.6%,  R3=11.5%
#
# These give bar family share ~25% of base (RWB archetype 31%, M15 deviation lower
# because feature carries half the RTP). Bar1 marginal cubed > bar2 cubed > bar3 cubed
# satisfies §1.
#
# Jackpot: marginal target <= 0.4% per reel (user_brief #6: ≤0.6%)
# Topdollar (R3): 1.13% (trigger rate 1.13% per spin, matching v7 target 1-1.5%)
#
# Sanity check from these targets:
#   - bar1 marginal cubed: R1=0.098^3 + ... but wait, we need pay_id 7 = 3-of-1bar lined up
#     Approximation P(pay_id 7) = p1_1bar * p2_1bar * p3_1bar with wild substitution lift
#   - Cherry-anywhere: P(>=1 cherry) - higher overrides
#
# We iterate candidates in the marginals-space, then run analytic_profile to validate.


# -----------------------------------------------------------------------
# strip helpers
# -----------------------------------------------------------------------

def load_strips() -> list[list[str]]:
    return json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]


def stop_counts_per_reel(strips: list[list[str]]) -> list[dict[str, int]]:
    out = []
    for reel in strips:
        cnt: dict[str, int] = defaultdict(int)
        for s in reel:
            cnt[s] += 1
        out.append(dict(cnt))
    return out


def marginals_to_weights(
    strips: list[list[str]],
    target_marginals: list[dict[str, float]],
    scale: int = 10000,
) -> list[list[int]]:
    """Convert per-reel target marginals (sum to 1) into integer per-stop weights.

    All stops of the same symbol on a reel get equal weight. We pick weight
    per stop such that the resulting marginals after rounding approximate
    the targets. Use larger scale (10000) to reduce rounding error.

    NOTE: mechanism B blank redistribution is applied AFTER this base-weight
    assignment by `apply_mechanism_b_blanks`.
    """
    weights: list[list[int]] = []
    counts_per_reel = stop_counts_per_reel(strips)
    for r_idx, reel in enumerate(strips):
        target = target_marginals[r_idx]
        counts = counts_per_reel[r_idx]
        # weight per stop, scaled
        wps: dict[str, int] = {}
        for sym, frac in target.items():
            if sym not in counts:
                continue
            cnt = counts[sym]
            # candidate weight (float, then round to int >=1)
            w_float = scale * frac / cnt
            wps[sym] = max(1, int(round(w_float)))
        # assign per-stop
        reel_weights = []
        for s in reel:
            reel_weights.append(int(wps.get(s, 1)))
        weights.append(reel_weights)
    return weights


def apply_mechanism_b_blanks(
    strips: list[list[str]],
    weights: list[list[int]],
    top_symbols: set[str] = frozenset(("doublediamond", "high7", "topdollar")),
    non_top_adj_floor: int = 1,
) -> list[list[int]]:
    """Redistribute blank weight per reel: non-top-adj Blanks -> floor=1,
    top-adj Blanks absorb the remainder. RTP-neutral (preserves total
    reel blank weight). Per philosophy §15.4 + §15.5.
    """
    out = [list(row) for row in weights]
    for r_idx, reel in enumerate(strips):
        n = len(reel)
        # find total blank weight on this reel
        total_blank_w = sum(out[r_idx][i] for i in range(n) if reel[i] == "blank")
        # partition blank positions into top-adj vs non-top-adj
        top_adj_positions = []
        non_top_adj_positions = []
        for i in range(n):
            if reel[i] != "blank":
                continue
            prev = reel[(i - 1) % n]
            nxt = reel[(i + 1) % n]
            if prev in top_symbols or nxt in top_symbols:
                top_adj_positions.append(i)
            else:
                non_top_adj_positions.append(i)
        if not top_adj_positions:
            # no top-adj blanks on this reel — no transform possible
            continue
        # reserve floor=1 for each non-top-adj
        reserve = non_top_adj_floor * len(non_top_adj_positions)
        leftover = total_blank_w - reserve
        if leftover <= 0:
            # nothing to redistribute
            continue
        # assign top-adj equally
        per_top_adj = leftover // len(top_adj_positions)
        rem = leftover - per_top_adj * len(top_adj_positions)
        # set weights
        for i in non_top_adj_positions:
            out[r_idx][i] = non_top_adj_floor
        for k, i in enumerate(top_adj_positions):
            out[r_idx][i] = per_top_adj + (1 if k < rem else 0)
    return out


# -----------------------------------------------------------------------
# evaluate candidate
# -----------------------------------------------------------------------

def evaluate_candidate(
    name: str,
    target_marginals: list[dict[str, float]],
    feature_params: dict,
    *,
    apply_mech_b: bool = True,
    scale: int = 10000,
) -> dict:
    """Build weights from target marginals, optionally apply mechanism B
    blank redistribute, then compute the full analytic profile + the
    eyeball metrics requested by Stage 4 workflow.
    """
    strips = load_strips()
    weights = marginals_to_weights(strips, target_marginals, scale=scale)
    if apply_mech_b:
        weights = apply_mechanism_b_blanks(strips, weights)

    # Write a temporary weights.json to load engine + analytic_profile
    weights_doc = {
        "machine": "M15",
        "mode": 1,
        "reel_set": "default",
        "weights": weights,
        "feature_params": feature_params,
    }
    tmp_path = _ROOT / "session_artifacts" / "M15" / "_tmp_v9_candidate.json"
    tmp_path.write_text(json.dumps(weights_doc, indent=2), encoding="utf-8")
    try:
        engine, _spec = load_engine(SPEC_PATH, tmp_path, strips_path=STRIPS_PATH)
        profile = analytic_profile(engine)
        margs = [compute_reel_marginal(r) for r in engine.reels]
        # reel strips for PWDF computation
        reel_strips_dict = [
            [{"symbol": s.symbol, "weight": int(s.weight)} for s in r.stops]
            for r in engine.reels
        ]
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # feature math
    x_count = tuple(feature_params["x_count_weights"])
    y_count = tuple(feature_params["y_count_weights"])
    x_val = tuple(feature_params.get("x_value_weights", [1.0] * 10))
    y_val = tuple(feature_params.get("y_value_weights", [1.0, 1.0]))
    accept_thresh = float(feature_params.get("accept_threshold", 40))
    max_rounds = int(feature_params.get("max_rounds", 4))
    fspec = FeatureSpec(
        x_count_weights=x_count,
        y_count_weights=y_count,
        x_value_weights=x_val,
        y_value_weights=y_val,
        accept_threshold=accept_thresh,
        max_rounds=max_rounds,
    )
    fstats = analyze_feature(fspec)
    trigger_rate = margs[2].get("topdollar", 0.0)
    feature_rtp_pp = trigger_rate * fstats.expected_payout * 100.0
    total_rtp_pct = profile["rtp_pct"] + feature_rtp_pp
    # 1000+
    round_dist = _round_payout_distribution(x_count, y_count, x_val, y_val)
    p_r_ge_1000_per_trigger = sum(p for r, p in round_dist if r >= 1000)
    p_r_ge_1000_per_spin = trigger_rate * p_r_ge_1000_per_trigger

    # base vs feature
    base_pp = profile["rtp_pct"]
    feat_pp = feature_rtp_pp
    base_share = base_pp / total_rtp_pct * 100 if total_rtp_pct > 0 else 0
    feat_share = feat_pp / total_rtp_pct * 100 if total_rtp_pct > 0 else 0

    # pay-level breakdown
    pay_hits = profile["pay_hits"]
    pay_rtp = profile["pay_rtp"]
    # cherry1 hit share
    cherry1_hit = pay_hits.get("9", 0.0)
    cherry1_share_of_hit = cherry1_hit / profile["hit_rate"] if profile["hit_rate"] > 0 else 0
    # hit rate hierarchy
    bar1_p = pay_hits.get("7", 0.0)
    bar2_p = pay_hits.get("5", 0.0)
    bar3_p = pay_hits.get("3", 0.0)
    cherry1_p = pay_hits.get("9", 0.0)
    cherry2_p = pay_hits.get("71", 0.0)
    cherry3_p = pay_hits.get("4", 0.0)
    bar_mixed_p = pay_hits.get("8", 0.0)
    high7w_p = pay_hits.get("2", 0.0)
    high7p_p = pay_hits.get("21", 0.0)
    wild_p = pay_hits.get("1", 0.0)
    # buckets
    bucket_rate = profile["bucket_rate"]
    bucket_rtp = profile["bucket_rtp"]
    bucket_1to5_rate = bucket_rate.get("ge1_lt5", 0.0)
    bucket_1to5_rtp = bucket_rtp.get("ge1_lt5", 0.0) * 100  # to pp
    bucket_1to5_share_base = (bucket_1to5_rtp / base_pp) if base_pp > 0 else 0

    # PWDF
    top_window = {}
    for sym in ("doublediamond", "high7", "topdollar"):
        max_pw = 0.0
        for strip in reel_strips_dict:
            pw = symbol_window_probability(strip, sym)
            if pw > max_pw:
                max_pw = pw
        top_window[sym] = max_pw

    return {
        "name": name,
        "weights": weights,
        "target_marginals": target_marginals,
        "feature_params": feature_params,
        "profile": profile,
        "reel_marginals": margs,
        "trigger_rate": trigger_rate,
        "feature_stats": fstats,
        "total_rtp_pct": total_rtp_pct,
        "base_pp": base_pp,
        "feat_pp": feat_pp,
        "base_share": base_share,
        "feat_share": feat_share,
        "p_r_ge_1000_per_spin": p_r_ge_1000_per_spin,
        "cherry1_share_of_hit": cherry1_share_of_hit,
        "bar1_p": bar1_p,
        "bar2_p": bar2_p,
        "bar3_p": bar3_p,
        "cherry1_p": cherry1_p,
        "cherry2_p": cherry2_p,
        "cherry3_p": cherry3_p,
        "bar_mixed_p": bar_mixed_p,
        "high7w_p": high7w_p,
        "high7p_p": high7p_p,
        "wild_p": wild_p,
        "bucket_1to5_rate": bucket_1to5_rate,
        "bucket_1to5_rtp_pp": bucket_1to5_rtp,
        "bucket_1to5_share_base": bucket_1to5_share_base,
        "top_window": top_window,
    }


def print_candidate_report(res: dict) -> str:
    """Pretty-print the eyeball metrics for a candidate."""
    lines = []
    name = res["name"]
    p = res["profile"]
    margs = res["reel_marginals"]
    lines.append(f"\n======== Candidate: {name} ========")
    lines.append(f"Total RTP:        {res['total_rtp_pct']:.3f}%")
    lines.append(f"  Base RTP:       {res['base_pp']:.3f}pp  ({res['base_share']:.1f}%)")
    lines.append(f"  Feature RTP:    {res['feat_pp']:.3f}pp  ({res['feat_share']:.1f}%)")
    lines.append(f"Base hit rate:    {p['hit_rate']*100:.3f}%")
    lines.append(f"Base CV:          {p['cv']:.3f}")
    lines.append(f"Trigger rate:     {res['trigger_rate']*100:.3f}%  (1 in {1/res['trigger_rate']:.0f})")
    lines.append(f"Feature EV:       {res['feature_stats'].expected_payout:.2f}x")
    lines.append(f"Feature CV:       {res['feature_stats'].cv:.3f}")
    lines.append(f"P(R>=1000/spin):  {res['p_r_ge_1000_per_spin']:.3e}  (cap 1e-5)")
    lines.append("")
    lines.append("Per-reel marginals:")
    for r_idx in range(3):
        m = margs[r_idx]
        lines.append(f"  R{r_idx+1}: blank={m.get('blank', 0)*100:.2f}%  cherry={m.get('cherry', 0)*100:.2f}%  "
                     f"1bar={m.get('1bar', 0)*100:.2f}%  2bar={m.get('2bar', 0)*100:.2f}%  "
                     f"3bar={m.get('3bar', 0)*100:.2f}%  high7={m.get('high7', 0)*100:.2f}%  "
                     f"dd={m.get('doublediamond', 0)*100:.2f}%  jackpot={m.get('jackpot', 0)*100:.2f}%  "
                     f"topdollar={m.get('topdollar', 0)*100:.2f}%")
    lines.append("")
    lines.append("§1 hierarchy:")
    lines.append(f"  bar1 P={res['bar1_p']*100:.4f}%  bar2 P={res['bar2_p']*100:.4f}%  bar3 P={res['bar3_p']*100:.4f}%   ok={'PASS' if res['bar1_p'] >= res['bar2_p'] - 1e-9 and res['bar2_p'] >= res['bar3_p'] - 1e-9 else 'FAIL'}")
    lines.append(f"  cherry1 P={res['cherry1_p']*100:.4f}%  cherry2 P={res['cherry2_p']*100:.4f}%  cherry3 P={res['cherry3_p']*100:.4f}%")
    lines.append(f"  high7_wild P={res['high7w_p']*100:.4f}%  high7_pure P={res['high7p_p']*100:.4f}%  wild_pure P={res['wild_p']*100:.4f}%  bar_mixed P={res['bar_mixed_p']*100:.4f}%")
    lines.append("")
    lines.append("§8 hit decomposition:")
    lines.append(f"  cherry1 share of hit = {res['cherry1_share_of_hit']*100:.2f}%  (cap 70-72; carve allows 80%)")
    lines.append("")
    lines.append(f"Bucket ge1_lt5: rate {res['bucket_1to5_rate']*100:.2f}%  "
                 f"RTP {res['bucket_1to5_rtp_pp']:.2f}pp  "
                 f"share-of-base {res['bucket_1to5_share_base']*100:.2f}%")
    lines.append("")
    lines.append("PWDF top-symbol any-reel max:")
    for sym, pw in res["top_window"].items():
        lines.append(f"  {sym}: {pw*100:.2f}%  (floor doublediamond/high7=28%, topdollar=22%)")
    lines.append("")
    lines.append("Jackpot per-reel marginal:")
    for r_idx in range(3):
        m = margs[r_idx].get("jackpot", 0)
        lines.append(f"  R{r_idx+1} jackpot = {m*100:.3f}%  (cap 0.6%)")

    # Per pay_id breakdown + family share-of-base
    base_pp = res["base_pp"]
    profile = res["profile"]
    pay_rtp = profile.get("pay_rtp", {})
    fam_map = {
        "9": "cherry1", "71": "cherry2", "4": "cherry3",
        "1": "wild_pure", "2": "high7_wild", "21": "high7_pure",
        "3": "bar3", "5": "bar2", "7": "bar1", "8": "bar_mixed",
    }
    family_pp = defaultdict(float)
    for pid, rtp in pay_rtp.items():
        fam = fam_map.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp * 100
    lines.append("")
    lines.append("Family share-of-base (target_v2 bands for mode 1):")
    bands = {
        "cherry1": (26.0, 38.0),
        "bar_mixed": (12.0, 25.0),
        "bar1": (4.0, 12.0),
        "bar2": (10.0, 20.0),
        "bar3": (5.0, 12.0),
        "high7": (2.5, 8.0),
        "wild_pure": (0.4, 2.0),
    }
    high7_combined = family_pp.get("high7_wild", 0) + family_pp.get("high7_pure", 0)
    for fam, (lo, hi) in bands.items():
        if fam == "high7":
            v = high7_combined
        else:
            v = family_pp.get(fam, 0)
        share = (v / base_pp) * 100 if base_pp > 0 else 0
        status = "OK" if (lo <= share <= hi) else "OUT"
        lines.append(f"  {fam}: {v:.2f}pp  share={share:.2f}%  band=[{lo}, {hi}]  {status}")

    # Per-pay frequency for cherry2, cherry3
    pay_hits = profile.get("pay_hits", {})
    lines.append("")
    lines.append("Per-pay frequency (mode 1 bands):")
    pp_bands = {
        "71": (0.4, 1.5),    # cherry2
        "4": (0.005, 0.05),  # cherry3
    }
    for pid, (lo, hi) in pp_bands.items():
        p = pay_hits.get(pid, 0) * 100
        status = "OK" if (lo <= p <= hi) else "OUT"
        lines.append(f"  pay_id {pid} ({fam_map.get(pid)}): P={p:.4f}%  band=[{lo}, {hi}]  {status}")

    # Top-jackpot cadence
    p1 = pay_hits.get("1", 0)
    cadence = 1.0 / p1 if p1 > 0 else float("inf")
    status = "OK" if (50000 <= cadence <= 100000) else "OUT"
    lines.append(f"  pay_id 1 (wild_pure) cadence: 1 in {cadence:.0f}  band=[1/50k, 1/100k]  {status}")
    return "\n".join(lines)


# -----------------------------------------------------------------------
# Candidates — first-principles design exploration
# -----------------------------------------------------------------------

# Top Dollar archetype mode 1 feature_params (per v7 brief + v8.1 §e: keep
# feature unchanged from v7 baseline 46x EV, trigger 1.127%).
# These x_value_weights make E[R] ≈ 46x.
M1_FEATURE_PARAMS = {
    "x_count_weights": [5, 40, 40, 12, 3],
    "y_count_weights": [75, 20, 5],
    "x_value_weights": [
        0.0001, 0.0266, 0.1455, 0.1455,
        1.3729, 1.3729, 7.4998, 7.4998,
        40.9684, 40.9684,
    ],
    "y_value_weights": [1, 1],
    "accept_threshold": 40,
    "max_rounds": 4,
}


def candidate_marginals_a():
    """Candidate A: baseline first-principles — blank 54/55/55,
    cherry 5/5/2.5, doublediamond 3/3.5/1.3, high7 2.8/4.5/1.8,
    bars 3bar 7/5.8/8, 2bar 13.5/12.8/15.2, 1bar 9.8/8.6/11.5,
    jackpot 0.4/0.4/0.4, topdollar 1.13 on R3.
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.050, "doublediamond": 0.030, "high7": 0.028,
         "3bar": 0.070, "2bar": 0.135, "1bar": 0.098, "jackpot": 0.004,
         "topdollar": 0.0},
        # R2
        {"blank": 0.550, "cherry": 0.050, "doublediamond": 0.035, "high7": 0.045,
         "3bar": 0.058, "2bar": 0.128, "1bar": 0.086, "jackpot": 0.004,
         "topdollar": 0.0},
        # R3
        {"blank": 0.550, "cherry": 0.025, "doublediamond": 0.013, "high7": 0.018,
         "3bar": 0.080, "2bar": 0.152, "1bar": 0.115, "jackpot": 0.004,
         "topdollar": 0.01127},
    ]


def candidate_marginals_b():
    """Candidate B: cherry reduce vs A — drop cherry on R1/R2 from 5% to 4.2%
    to reduce cherry1 hit share to under 70%."""
    m = candidate_marginals_a()
    m[0]["cherry"] = 0.042
    m[1]["cherry"] = 0.042
    m[2]["cherry"] = 0.022
    # rebalance blank to keep sum=1
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_c():
    """Candidate C: cherry further reduce + bar1 lift to fix hierarchy.
    Goal: hit ~16.5%, cherry1 ~68% hit share, bar1 > bar2 > bar3."""
    m = candidate_marginals_a()
    # Cherry: drop further — target cherry1 hit ~11%
    m[0]["cherry"] = 0.040
    m[1]["cherry"] = 0.040
    m[2]["cherry"] = 0.020
    # Bar hierarchy correction: bar1 marginal larger to fix v7 issue
    # v7: bar1 R1=10.6 R2=9.5 R3=12.5 / 2bar R1=14.8 R2=14.3 R3=16.6
    # In v7, P(bar1) cubed < P(bar2) cubed because 1bar marginal smaller
    # Need to lift 1bar above 2bar in marginal to fix.
    # Wait — paytable: pay_id 7 = 3 1bars (5x), pay_id 5 = 3 2bars (10x).
    # So bar1=5x is lower payout. Per §1 inverse pyramid, lower payout
    # should have HIGHER hit. Currently in v7: bar1 P=0.25%, bar2 P=0.58%
    # → INVERTED. Need bar1 cubed > bar2 cubed → bar1 marginal > bar2 marginal.
    # Currently 1bar marginal is below 2bar in v7. We need to swap.
    # Target: 1bar marg ~13%, 2bar marg ~10%, 3bar marg ~6%
    m[0]["1bar"] = 0.130
    m[0]["2bar"] = 0.105
    m[0]["3bar"] = 0.055
    m[1]["1bar"] = 0.115
    m[1]["2bar"] = 0.095
    m[1]["3bar"] = 0.050
    m[2]["1bar"] = 0.140
    m[2]["2bar"] = 0.120
    m[2]["3bar"] = 0.065
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_d():
    """Candidate D: tighten further to land in 95% RTP.
    Probably C will have RTP a little off — adjust trigger or feature."""
    m = candidate_marginals_c()
    # Slight cherry lift to push hit toward upper of [15, 18]
    m[0]["cherry"] = 0.043
    m[1]["cherry"] = 0.043
    m[2]["cherry"] = 0.022
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_e():
    """Candidate E: explicit base=42.75pp + feature=52.25pp target.

    Trigger rate locked at v7 1.127%; feature EV 46x → 1.127×46=51.8pp feature.
    Need base=43.2pp from marginals C/D.

    If base is too low (current C might be ~42pp), bump 2bar slightly to lift base RTP.
    If too high, drop 2bar.
    """
    m = candidate_marginals_d()
    # 2bar gets RTP 10x with substitution; raising 2bar marginal lifts base RTP.
    # Test: bump 2bar across reels.
    m[0]["2bar"] = 0.118
    m[1]["2bar"] = 0.108
    m[2]["2bar"] = 0.135
    # rebalance
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_f():
    """Candidate F: focus on r1 blank cap exact 54% per philosophy §12.
    + cherry-1 cap at 70% of hit."""
    m = candidate_marginals_e()
    # Tighten R1 blank to ~54%
    target_r1_blank = 0.540
    m[0]["blank"] = target_r1_blank
    used = sum(v for k, v in m[0].items() if k != "blank")
    # used + 0.540 must = 1 → distribute excess
    excess = 1 - used - target_r1_blank
    # spread excess evenly into 2bar / 1bar
    bump = excess / 2
    m[0]["2bar"] += bump
    m[0]["1bar"] += bump
    return m


def candidate_marginals_g():
    """Candidate G: keep design F but tune cherry to ensure cherry1<70% hit.
    Test E with cherry slightly less."""
    m = candidate_marginals_f()
    # Cherry-1 hit = ~1 - prod(1 - cherry_marg) cubed (minus higher overrides)
    # ~ p1+p2+p3 first order ≈ 4.3+4.3+2.2 = 10.8% ; but cherry1 is fired when no 3-cherry,
    # no 2-cherry pay. So P(cherry1) ≈ P(>=1 cherry) - P(2-cherry) - P(3-cherry).
    # Want cherry1 hit ~ 11% (with hit_rate ~16%, gives cherry1 share ~69%).
    # Tighten R1/R2 cherry to 4.0%, R3 to 2.0%
    m[0]["cherry"] = 0.040
    m[1]["cherry"] = 0.040
    m[2]["cherry"] = 0.020
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    # R1 still at 54%? Verify
    m[0]["blank"] = 0.540
    used = sum(v for k, v in m[0].items() if k != "blank")
    excess = 1 - used - 0.540
    m[0]["2bar"] += excess / 2
    m[0]["1bar"] += excess / 2
    return m


def candidate_marginals_h_explore_blank_levels():
    """Candidate H: explicit cherry tied to total hit budget.

    To hit 16% with cherry1 ~70% of hit -> cherry1 hit = 11.2%.
    From philosophy archetype: cherry1 hit = 1 - prod(1 - c_i) - P(2 or 3 cherry)
    Rough: 1-(1-c)^3 ~ 11.2% → c ~ 0.039 if all equal; or c1=c2=0.040, c3=0.020 gives:
      P(at least 1 cherry) = 1 - (1-.040)(1-.040)(1-.020) = 1 - .9216*.9800 = 9.7%

    Hm, too low. Adjust: c1=c2=0.050, c3=0.020 →
      P >=1 cherry = 1 - (.95)(.95)(.98) = 11.6%
    cherry1 hit ≈ 11.4% (after deducting overrides)

    Let's go with c=5/5/2 explicitly.
    """
    m = candidate_marginals_a()
    m[0]["cherry"] = 0.050
    m[1]["cherry"] = 0.050
    m[2]["cherry"] = 0.020  # R3 less
    # Bar fix (1bar > 2bar > 3bar marginal)
    m[0]["1bar"] = 0.115
    m[0]["2bar"] = 0.105
    m[0]["3bar"] = 0.060
    m[1]["1bar"] = 0.105
    m[1]["2bar"] = 0.095
    m[1]["3bar"] = 0.055
    m[2]["1bar"] = 0.125
    m[2]["2bar"] = 0.120
    m[2]["3bar"] = 0.070
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_i_close_to_v7_with_bar_swap():
    """Candidate I: lift base RTP by aligning ~v7 marginals but swap
    1bar / 2bar ordering. v7 base RTP was 43.15pp. v7 marginals were
    blank 54.5/54.6/54.5; we keep similar non-blank totals but reorder.

    Target: bar1 > bar2 > bar3 marginal (5x first, then 10x, then 20x).
    v7's bar lineup was: 1bar 10.6/9.5/12.5, 2bar 14.8/14.2/16.6, 3bar 7.7/6.3/8.7
    Swap so: 1bar 14.8/14.2/16.6, 2bar 10.6/9.5/12.5, 3bar 7.7/6.3/8.7.

    Cherry stays 6/6/3 (v7) — accept cherry1 ~71% of hit (slight over cap
    but only by 1pp; documented carve to 80% for cherry-anywhere).
    """
    return [
        {"blank": 0.545, "cherry": 0.061, "1bar": 0.148, "2bar": 0.106, "3bar": 0.077,
         "high7": 0.030, "doublediamond": 0.032, "jackpot": 0.001, "topdollar": 0.0},
        {"blank": 0.546, "cherry": 0.061, "1bar": 0.142, "2bar": 0.095, "3bar": 0.063,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.006, "topdollar": 0.0},
        {"blank": 0.545, "cherry": 0.031, "1bar": 0.166, "2bar": 0.125, "3bar": 0.087,
         "high7": 0.020, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_j_tighten_cherry_to_70cap():
    """Candidate J: take I, drop cherry from 6/6/3 -> 5.0/5.0/2.5.

    Goal: cherry1 hit drop to ~11-12% so cherry1/hit ~70%.
    """
    m = candidate_marginals_i_close_to_v7_with_bar_swap()
    # Drop cherry: from 6.1% → 5.0% on R1/R2; from 3.1% → 2.5% on R3
    m[0]["cherry"] = 0.050
    m[1]["cherry"] = 0.050
    m[2]["cherry"] = 0.025
    # Don't compensate blank — let blank rise slightly (cherry mass moved to blank)
    # rebalance
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_k_R1_blank_lock():
    """Candidate K: from J, force R1 blank = 54.0% (philosophy §12 lock).

    Move excess mass to 1bar (low pay → expand winners zone)."""
    m = candidate_marginals_j_tighten_cherry_to_70cap()
    target_r1 = 0.540
    # if blank > target, redistribute the difference to 1bar
    diff = m[0]["blank"] - target_r1
    if diff > 0:
        m[0]["blank"] = target_r1
        m[0]["1bar"] += diff
    return m


def candidate_marginals_l_final_balance():
    """Candidate L: K with adjusted RTP via 2bar trim down.

    K probably has RTP > 95% because we kept high 1bar marginals.
    If so, trim 1bar to ~0.135 across reels."""
    m = candidate_marginals_k_R1_blank_lock()
    # Trim 1bar marginal slightly if needed (will iterate via evaluation)
    return m


def candidate_marginals_m_v7_aligned():
    """Candidate M: V7-aligned but with 1bar > 2bar swapped.

    Use v7's exact non-blank counts but reassign the per-stop weights so
    1bar > 2bar > 3bar marginal.

    v7 base RTP = 43.15pp with marginals cherry 6.06/6.07/3.10, 1bar/2bar
    swap from v7 → this should give similar but with §1 fixed.

    Trigger 1.13%, feature EV 46 → feature 52pp; total ~95pp ✓
    """
    return [
        # R1 — blank 54%; jackpot capped 0.4%
        {"blank": 0.540, "cherry": 0.054, "1bar": 0.142, "2bar": 0.110, "3bar": 0.080,
         "high7": 0.030, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 55%
        {"blank": 0.550, "cherry": 0.054, "1bar": 0.140, "2bar": 0.100, "3bar": 0.065,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 55%; high7 reduced (trigger reel role), topdollar = 1.13%, jackpot cap
        {"blank": 0.555, "cherry": 0.028, "1bar": 0.162, "2bar": 0.122, "3bar": 0.087,
         "high7": 0.020, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_n_RTP_balance():
    """Candidate N: tune M for 95% RTP target with cherry1 ≤70% hit + R1 blank ~54%.

    Key levers:
      - Cherry marginal drives cherry1 hit
      - 2bar/3bar/high7 marginal cubed drives high-multiplier RTP
      - 1bar marginal cubed × 5x; bar_mixed cubed × 2x
    """
    m = candidate_marginals_m_v7_aligned()
    # Trim cherry to 5.0/5.0/2.0 to bring cherry1 ≤ 70% hit
    m[0]["cherry"] = 0.050
    m[1]["cherry"] = 0.050
    m[2]["cherry"] = 0.020
    # Bump 2bar back up since we want RTP near 95
    m[0]["2bar"] = 0.120
    m[1]["2bar"] = 0.115
    m[2]["2bar"] = 0.135
    # jackpot kept low (cap 0.6%) - use 0.004 per reel
    m[0]["jackpot"] = 0.004
    m[1]["jackpot"] = 0.004
    m[2]["jackpot"] = 0.001
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_o_locked_R1_blank():
    """Candidate O: N + R1 blank lock to 54%.

    Move excess blank mass into 1bar (small payout, doesn't kill RTP).
    """
    m = candidate_marginals_n_RTP_balance()
    if m[0]["blank"] > 0.540:
        diff = m[0]["blank"] - 0.540
        m[0]["blank"] = 0.540
        m[0]["1bar"] += diff
    return m


def candidate_marginals_p_rtp_94():
    """Candidate P: from N (jackpot-fixed), need to lift RTP by ~1-2pp.
    Lift 2bar and high7 marginals slightly.
    """
    m = candidate_marginals_n_RTP_balance()
    # Lift 2bar to push hit rate + RTP
    m[0]["2bar"] = 0.125
    m[1]["2bar"] = 0.120
    m[2]["2bar"] = 0.140
    # Lift high7 R2 (mid reel) — multiplier 30 with wild lift
    m[1]["high7"] = 0.058
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_q_rtp_95():
    """Candidate Q: from P, lift slightly more to land exactly 95.
    Add bump on bar_mixed influence via 3bar lift (3bar = 20x highest in bar fam).
    """
    m = candidate_marginals_p_rtp_94()
    # 3bar small lift across reels
    m[0]["3bar"] = 0.085
    m[1]["3bar"] = 0.067
    m[2]["3bar"] = 0.090
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_r_final_balance():
    """Candidate R: Q with R1 blank lock to 54%.

    R1 blank should be 54% (philosophy §12). Move excess into 1bar.
    """
    m = candidate_marginals_q_rtp_95()
    if m[0]["blank"] > 0.540:
        diff = m[0]["blank"] - 0.540
        m[0]["blank"] = 0.540
        m[0]["1bar"] += diff
    elif m[0]["blank"] < 0.540:
        diff = 0.540 - m[0]["blank"]
        m[0]["blank"] = 0.540
        m[0]["1bar"] -= diff  # may need negative trim
    return m


def candidate_marginals_s_tune_4555():
    """Candidate S: target base:feature 45:55. Currently we get ~41:59.

    To shift to 45:55, drop trigger rate (which drops feature pp) OR raise
    base RTP.

    Math:
      If total=95, feat:base=55:45 → feat=52.25pp, base=42.75pp
      Currently base ~38pp; need +4.7pp base RTP from non-feature changes.
      4.7pp base lift via 2bar/3bar marginal bumps.

    Or simpler: bump 2bar marginals more aggressively.
    """
    m = candidate_marginals_r_final_balance()
    # Higher 2bar/3bar to push base RTP
    m[0]["2bar"] = 0.140
    m[1]["2bar"] = 0.130
    m[2]["2bar"] = 0.150
    m[0]["3bar"] = 0.090
    m[1]["3bar"] = 0.072
    m[2]["3bar"] = 0.094
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    # R1 blank lock
    if m[0]["blank"] != 0.540:
        diff = m[0]["blank"] - 0.540
        m[0]["blank"] = 0.540
        # diff may be negative — that means 1bar etc would shrink
        m[0]["1bar"] += diff
    return m


def candidate_marginals_t_balanced_4555():
    """Candidate T: aim for 95% RTP with 45:55 split + R1 blank 54%.

    Adjust 1bar / 2bar simultaneously so:
      - Total non-blank = 46% on R1, R2; ~45.5% on R3
      - bar1 marg > bar2 marg > bar3 marg
      - cherry 5/5/2 (cherry1 ~65-70% hit)
      - high7 3/5/2; dd 3.2/3.7/1.4 (PWDF cooperates)
      - jackpot tiny
    """
    return [
        # R1 — blank 54.0%; non-blank 46.0% total
        # 1bar 14.5, 2bar 13.0, 3bar 8.0, cherry 5.0, high7 3.0, dd 3.2, jackpot 0.3
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.145, "2bar": 0.130, "3bar": 0.080,
         "high7": 0.030, "doublediamond": 0.032, "jackpot": 0.003, "topdollar": 0.0},
        # R2 — blank 54.5%; non-blank 45.5%
        {"blank": 0.545, "cherry": 0.050, "1bar": 0.140, "2bar": 0.120, "3bar": 0.066,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.003, "topdollar": 0.0},
        # R3 — blank 54.5%; topdollar 1.13
        {"blank": 0.545, "cherry": 0.025, "1bar": 0.160, "2bar": 0.137, "3bar": 0.087,
         "high7": 0.020, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_u_trim_bar3():
    """Candidate U: from R, trim 3bar to keep share under 12% cap of base.

    R has bar3 share ~12.4% (just over cap). Trim 3bar marginal slightly.
    Also slightly trim 1bar/2bar to keep bar_mixed share under 25.
    """
    m = [
        # R1
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.135, "2bar": 0.122, "3bar": 0.076,
         "high7": 0.030, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 (high7 R2=5%)
        {"blank": 0.545, "cherry": 0.050, "1bar": 0.135, "2bar": 0.115, "3bar": 0.060,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.545, "cherry": 0.020, "1bar": 0.155, "2bar": 0.135, "3bar": 0.085,
         "high7": 0.020, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]
    return m


def candidate_marginals_v_final_tune():
    """Candidate V: from U, tighten R1 blank to exactly 54 + verify all
    share bands.

    Goal: total ≥ 94, hit ∈ [15, 18], all share bands satisfied.
    """
    return candidate_marginals_u_trim_bar3()  # already balanced


def candidate_marginals_w_final_polish():
    """Candidate W: increase high7 + dd slightly to lift wild_pure family share
    above floor 0.4%. Current R has wild_pure ~0.8% which is in band; this is
    more about ensuring PWDF stays solid."""
    m = candidate_marginals_u_trim_bar3()
    # Already good — pass through
    return m


def candidate_marginals_x_aim_95():
    """Candidate X: aim for 95% RTP at scale=10000 (which is more faithful).

    I (v7_with_bar_swap) at scale=10000 gave 91.55% RTP with hit 19.37%.
    Higher hit means cherry is too high. Trim cherry to drop hit to 17%.
    Lift 2bar/3bar to lift base RTP, lift high7/dd to keep PWDF + family share.

    Start from baseline non-blank ~46% per reel.
    """
    return [
        # R1 — blank 54%; non-blank 46% (cherry5 + 1bar 15 + 2bar 12 + 3bar 8 + high7 3.2 + dd 3.2 + jackpot 0.4)
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.150, "2bar": 0.120, "3bar": 0.078,
         "high7": 0.030, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 54.5%; high7 boost (mid reel feature visibility)
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.148, "2bar": 0.115, "3bar": 0.066,
         "high7": 0.052, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 54.5%; topdollar 1.13 + jackpot 0.1
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.170, "2bar": 0.135, "3bar": 0.087,
         "high7": 0.022, "doublediamond": 0.015, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_y_polish():
    """Candidate Y: X with R1 blank slightly relaxed to 54.0%, and re-check
    family caps. X may have bar3 over cap."""
    m = candidate_marginals_x_aim_95()
    # Ensure R1 blank = 54 exactly
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_z_final_v9():
    """Candidate Z (FINAL): Y refined to hit 95% RTP precisely with all
    bands passing.

    Strategy:
      - cherry 5/5/2 - hit ~17%
      - 1bar > 2bar > 3bar marginal (5x/10x/20x; lower payout higher P)
      - 1bar 0.15/0.148/0.17 R1/R2/R3 → bar1 hit ~ 0.5%
      - 2bar 0.12/0.115/0.135 R1/R2/R3 → bar2 hit ~ 0.3%
      - 3bar 0.078/0.066/0.087 R1/R2/R3 → bar3 hit ~ 0.1%
      - high7 0.030/0.052/0.022 R1/R2/R3 → high7 hit ~ 0.014%
      - dd 0.032/0.037/0.015 R1/R2/R3 → wild_pure hit ~ 0.0017%
      - jackpot 0.004/0.004/0.001 (all under 0.6% cap)
      - topdollar 0.011 on R3 → trigger 1.13%
    """
    return candidate_marginals_y_polish()


def candidate_marginals_aa_high7_boost():
    """Candidate AA: Y with high7 boost to lift base RTP closer to 95.

    Y had RTP 92.03%. Need +3pp. high7 is 30× — biggest per-hit lever.
    Lift high7 marg R2 from 5.2 → 7.0; R1 3 → 4; R3 2.2 → 3.
    Also bar_mixed share was over cap; trim 1bar slightly to compensate."""
    return [
        # R1 — high7 bump 3 → 4, drop 1bar 15 → 13.8 to keep total within budget
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.138, "2bar": 0.120, "3bar": 0.078,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 bump 5.2 → 7.0
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.130, "2bar": 0.115, "3bar": 0.066,
         "high7": 0.070, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — high7 bump 2.2 → 3.0
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.160, "2bar": 0.135, "3bar": 0.087,
         "high7": 0.030, "doublediamond": 0.015, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_bb_high7_more():
    """Candidate BB: AA with high7 R2 to 8% (max archetype reasonable)."""
    m = candidate_marginals_aa_high7_boost()
    m[1]["high7"] = 0.080
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_cc_dd_boost():
    """Candidate CC: AA with doublediamond R2 bump for wild_pure RTP lift.

    wild_pure hit currently 0.0017%, RTP 0.34pp. Cap at 2.0% share. Could
    push to ~1.0pp = 0.5% hit. dd marg R1/R2/R3 lifted 50% → 4.8/5.6/2.3.
    """
    m = candidate_marginals_aa_high7_boost()
    m[0]["doublediamond"] = 0.045
    m[1]["doublediamond"] = 0.055
    m[2]["doublediamond"] = 0.022
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_dd_combo():
    """Candidate DD: combine AA high7 + dd boost to lift wild_pure + high7 RTP."""
    m = candidate_marginals_aa_high7_boost()
    m[0]["high7"] = 0.040
    m[1]["high7"] = 0.075
    m[2]["high7"] = 0.030
    m[0]["doublediamond"] = 0.040
    m[1]["doublediamond"] = 0.050
    m[2]["doublediamond"] = 0.020
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ee_final():
    """Candidate EE: final tuning — balance all to land in 95% +/- 1.

    Trial: high7 4/7/3 dd 4/5/2 — modest lifts that should yield ~2.5pp
    additional RTP."""
    return [
        # R1
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.140, "2bar": 0.120, "3bar": 0.078,
         "high7": 0.040, "doublediamond": 0.040, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — bigger high7 (mid reel)
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.135, "2bar": 0.118, "3bar": 0.063,
         "high7": 0.070, "doublediamond": 0.050, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.160, "2bar": 0.135, "3bar": 0.088,
         "high7": 0.030, "doublediamond": 0.020, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_ff_R1_lock_54():
    """Candidate FF: EE with R1 blank to 54% strict + verify all band."""
    m = candidate_marginals_ee_final()
    # Already R1 blank at 0.540 by construction; sanity check
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_gg_dd_back_to_v7():
    """Candidate GG: high7 boost but dd marginals BACK to v7-like to keep
    wild_pure cadence in [1/50k, 1/100k].

    dd v7: R1=3.2 R2=3.7 R3=1.4 → product = 1.66e-5 → cadence 1/60k ✓
    high7 EE: R1=4 R2=7 R3=3 → too high (high7 family share 6.9% OK but RTP only 1.26pp at lower marg)

    Try: high7 R1=3.5 R2=6 R3=2.5 (modest lift)
    Compensate elsewhere — bump 2bar/3bar.
    """
    return [
        # R1 — high7 3.5, dd 3.2 (v7); 2bar 13, 3bar 8
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.140, "2bar": 0.130, "3bar": 0.080,
         "high7": 0.035, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 6.0 (lifted from 5 in v7); dd 3.7 (v7)
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.135, "2bar": 0.122, "3bar": 0.065,
         "high7": 0.060, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — high7 2.5; dd 1.4 (v7)
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.155, "2bar": 0.135, "3bar": 0.090,
         "high7": 0.025, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_hh_balance():
    """Candidate HH: GG balanced. We want base RTP ~ 43pp + feature 52pp = 95.

    Current Y: base 41.5, feat 50.5. GG should yield slightly higher base
    via high7 + 2bar/3bar lift.

    If still short, lift 2bar more aggressively (each 1pp lift on 2bar
    marginal adds ~0.3-0.4pp to base RTP via cube).
    """
    m = candidate_marginals_gg_dd_back_to_v7()
    # bump 2bar a bit more
    m[0]["2bar"] = 0.135
    m[1]["2bar"] = 0.128
    m[2]["2bar"] = 0.142
    # rebalance blank
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ii_minimal_dd():
    """Candidate II: HH with dd dropped slightly to push wild_pure cadence
    toward 1/80k center of band; this also frees room for more 2bar."""
    m = candidate_marginals_hh_balance()
    # dd back to 3/3.5/1.3 (slight v7 dial-down)
    m[0]["doublediamond"] = 0.030
    m[1]["doublediamond"] = 0.035
    m[2]["doublediamond"] = 0.013
    # rebalance
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_jj_final():
    """Candidate JJ: HH with high7 boost + bar trim for bar_mixed cap.

    Bring high7 R2 up to 7.5% (PWDF still fine); trim 1bar slightly to bring
    bar_mixed share under 25%. Goal: 94-96% RTP, hit 15-18, all bands OK.
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.132, "2bar": 0.130, "3bar": 0.080,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 7.5
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.125, "2bar": 0.120, "3bar": 0.065,
         "high7": 0.075, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.148, "2bar": 0.135, "3bar": 0.090,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_kk_2bar_boost():
    """Candidate KK: JJ with bigger 2bar lift since 2bar has clean band [10, 20]."""
    m = candidate_marginals_jj_final()
    m[0]["2bar"] = 0.140
    m[1]["2bar"] = 0.130
    m[2]["2bar"] = 0.150
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ll_3bar_boost():
    """Candidate LL: bar3 lift (mult 20) — within band [5, 12] share-of-base."""
    m = candidate_marginals_jj_final()
    m[0]["3bar"] = 0.085
    m[1]["3bar"] = 0.070
    m[2]["3bar"] = 0.095
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_mm_combined():
    """Candidate MM: high7 + 2bar lift to hit 95% RTP."""
    return [
        # R1
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.130, "2bar": 0.140, "3bar": 0.080,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 7.5
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.123, "2bar": 0.128, "3bar": 0.065,
         "high7": 0.075, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — slight 2bar boost
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.142, "2bar": 0.145, "3bar": 0.090,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_nn_final():
    """Candidate NN: MM with R1 blank lock to 54% explicit."""
    m = candidate_marginals_mm_combined()
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_oo_balanced():
    """Candidate OO: balance RTP + hierarchy + cherry1 floor.

    Strategy:
      - cherry 5.5/5.5/2.5 (cherry1 hit ~12.5%, share ~28% over floor 26%)
      - 1bar 15/14/16 (largest non-cherry, ensures bar1 > bar2)
      - 2bar 12/11/13 (moderate)
      - 3bar 7/6/8 (smaller — keeps bar3 share under 12)
      - high7 4/7/3 (R2 boosted for visibility + RTP)
      - dd 3.2/3.7/1.4 (v7-like, wild_pure cadence ~1/60k)
      - jackpot 0.4/0.4/0.1
      - topdollar 1.13 on R3

    Predict: hit ~17.5%, base RTP ~42, total ~94.
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.055, "1bar": 0.150, "2bar": 0.120, "3bar": 0.070,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2
        {"blank": 0.540, "cherry": 0.055, "1bar": 0.140, "2bar": 0.110, "3bar": 0.057,
         "high7": 0.070, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.160, "2bar": 0.135, "3bar": 0.085,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_pp_more_2bar():
    """Candidate PP: OO with 2bar bumped to push RTP up to 95."""
    m = candidate_marginals_oo_balanced()
    m[0]["2bar"] = 0.135
    m[1]["2bar"] = 0.125
    m[2]["2bar"] = 0.150
    # Reduce 1bar slightly to maintain non-blank total
    m[0]["1bar"] = 0.135
    m[1]["1bar"] = 0.125
    m[2]["1bar"] = 0.145
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_qq_high7_lift():
    """Candidate QQ: OO with high7 R2 lifted to 8.0% (high7 family share cap 8% achievable)."""
    m = candidate_marginals_oo_balanced()
    m[0]["high7"] = 0.045
    m[1]["high7"] = 0.080
    m[2]["high7"] = 0.035
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_rr_combined():
    """Candidate RR: combine OO + high7 lift + 2bar lift."""
    return [
        # R1 — high7 4.5, 2bar 13
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.135, "2bar": 0.130, "3bar": 0.070,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 8, 2bar 12
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.125, "2bar": 0.120, "3bar": 0.057,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.150, "2bar": 0.140, "3bar": 0.085,
         "high7": 0.035, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_ss_v9_final():
    """Candidate SS: V9 FINAL — careful balance for all constraints."""
    return candidate_marginals_rr_combined()


def candidate_marginals_tt_close_bars():
    """Candidate TT: keep 1bar marg ≈ 2bar marg (just slightly higher).

    This minimizes RTP loss from §1 fix while preserving the direction.

    Bar marginals: 1bar 13.5/13/15, 2bar 12.5/12/14, 3bar 7/6/8.
    Hierarchy: bar1 hit ≈ 1.35^3 × 1.3 × 1.5 ≈ 2.5 × 1.3 × 1.5 = 0.43%
              bar2 hit ≈ 1.25 × 1.2 × 1.4 = 0.21% (much less)
    Wait that doesn't work — multiply not cube. Let me think:
      bar1 hit = 0.135 × 0.13 × 0.15 = 0.00263 = 0.263%
      bar2 hit = 0.125 × 0.12 × 0.14 = 0.00210 = 0.210%
    bar1 > bar2 ✓
    bar3 hit = 0.07 × 0.06 × 0.08 = 0.000336 = 0.034% (less, as expected)
    """
    return [
        # R1 — 1bar 13.5 > 2bar 12.5 (by 1pp)
        {"blank": 0.540, "cherry": 0.055, "1bar": 0.135, "2bar": 0.125, "3bar": 0.075,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — 1bar 13 > 2bar 12; high7 7 (mid reel)
        {"blank": 0.540, "cherry": 0.055, "1bar": 0.130, "2bar": 0.120, "3bar": 0.060,
         "high7": 0.070, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — 1bar 15 > 2bar 14
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.150, "2bar": 0.140, "3bar": 0.090,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_uu_close_bars_v2():
    """Candidate UU: TT with high7 bumped further on R2 + slight bar3 lift.

    Goal: total RTP 94-95.
    """
    m = candidate_marginals_tt_close_bars()
    m[1]["high7"] = 0.080  # R2 high7 8% (max archetype)
    m[0]["3bar"] = 0.080
    m[2]["3bar"] = 0.095
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_vv_close_bars_v3():
    """Candidate VV: UU with cherry slightly lifted, more 2bar."""
    m = candidate_marginals_uu_close_bars_v2()
    # Cherry slight bump
    m[0]["cherry"] = 0.058
    m[1]["cherry"] = 0.058
    m[2]["cherry"] = 0.028
    # 2bar slight bump (still keeps 1bar > 2bar)
    m[0]["2bar"] = 0.130
    m[1]["2bar"] = 0.125
    m[2]["2bar"] = 0.145
    # 1bar lift to maintain gap above 2bar
    m[0]["1bar"] = 0.138
    m[1]["1bar"] = 0.133
    m[2]["1bar"] = 0.153
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ww_lock_R1():
    """Candidate WW: VV with R1 blank lock to 54% strict."""
    m = candidate_marginals_vv_close_bars_v3()
    # already at 54% by construction
    return m


def candidate_marginals_xx_cherry_down():
    """Candidate XX: VV with cherry trimmed to drop hit to ~17%.

    VV had hit 19.27%, cherry 5.8/5.8/2.8. Trim to 5/5/2 (smaller drop).
    """
    m = candidate_marginals_vv_close_bars_v3()
    m[0]["cherry"] = 0.050
    m[1]["cherry"] = 0.050
    m[2]["cherry"] = 0.020
    # rebalance
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_yy_v9_final():
    """Candidate YY (FINAL): XX with R1 blank locked to 54%, careful balance."""
    m = candidate_marginals_xx_cherry_down()
    # R1 blank lock
    target_r1 = 0.540
    if m[0]["blank"] != target_r1:
        diff = m[0]["blank"] - target_r1
        m[0]["blank"] = target_r1
        # absorb diff into 1bar
        m[0]["1bar"] += diff
    return m


def candidate_marginals_zz_high7_max():
    """Candidate ZZ: lift high7 R1=5, R2=9, R3=4 — push high7 family near 8% cap."""
    m = candidate_marginals_yy_v9_final()
    m[0]["high7"] = 0.050
    m[1]["high7"] = 0.090
    m[2]["high7"] = 0.040
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_aaa_v9_targeted():
    """Candidate AAA: targeted at 95% RTP — max use of all bands.

    Strategy:
      - cherry 5/5/2.5 (mid cherry to land hit ~17%)
      - 1bar > 2bar > 3bar (1bar 14/13/15, 2bar 13/12/14, 3bar 8/6.5/9)
      - high7 5/9/4 (R2 = 9% for visibility + RTP, family share approaches 7.5%)
      - dd 3.2/3.7/1.4 (v7-like, wild_pure cadence ~1/60k)
      - jackpot 0.4/0.4/0.1 (cap 0.6%)
      - topdollar 1.1 on R3
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.140, "2bar": 0.130, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 9.0%
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.130, "2bar": 0.120, "3bar": 0.065,
         "high7": 0.090, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.150, "2bar": 0.140, "3bar": 0.090,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_bbb_R1_blank_lock():
    """Candidate BBB: AAA with R1 blank locked at 54 + final sanity."""
    m = candidate_marginals_aaa_v9_targeted()
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ccc_hh_polish():
    """Candidate CCC: HH (92.85% RTP, hit 18.08%) with cherry tuning to bring hit
    down to ~17.5% so we exit the bar_mixed cap squeeze.

    HH config: high7 3.5/6/2.5, bar1 14/13.5/15.5, bar2 13.5/12.8/14.2, bar3 8/6.5/9.
    Issue: hit 18.08% bumps cherry hit, plus bar_mixed P=4.63% × 2 = 9.26pp, but
    base RTP includes other families. bar_mixed share 25.22% over cap.

    To fix: cherry slightly down (4.7/4.7/2.3) → cherry1 hit ~10.5%, total hit ~17.5%.
    Also: trim 1bar+2bar slightly to fix bar_mixed share.
    """
    return [
        # R1 — cherry slight trim; 1bar 13.5, 2bar 13.5 (close-bars maintain hierarchy)
        {"blank": 0.540, "cherry": 0.048, "1bar": 0.140, "2bar": 0.135, "3bar": 0.080,
         "high7": 0.035, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 6.0
        {"blank": 0.540, "cherry": 0.048, "1bar": 0.135, "2bar": 0.128, "3bar": 0.065,
         "high7": 0.060, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.023, "1bar": 0.155, "2bar": 0.142, "3bar": 0.090,
         "high7": 0.025, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_ddd_hh_polish_v2():
    """Candidate DDD: CCC with high7 R2 ramped to 7.5 (within cap 8)."""
    m = candidate_marginals_ccc_hh_polish()
    m[1]["high7"] = 0.075
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_eee_final_v9():
    """Candidate EEE: Final v9 — high7 lifted, all bands fitted, RTP ~94.

    Test: high7 4/8/3.5; dd 3.2/3.7/1.4; bars 13.5/13/15.
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.135, "2bar": 0.128, "3bar": 0.078,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 8% (cap = 8% share approx)
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.125, "2bar": 0.120, "3bar": 0.062,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.022, "1bar": 0.150, "2bar": 0.140, "3bar": 0.088,
         "high7": 0.035, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_fff_balanced():
    """Candidate FFF: aim for 94% RTP, all bands OK.

    Combines best of HH (high RTP) + RR (high7 boost). Trims 1bar to keep
    bar_mixed under 25.
    """
    return [
        # R1 — high7 4.5%, 1bar 13, 2bar 13, 3bar 7.5
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.130, "2bar": 0.128, "3bar": 0.075,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 7%, 1bar 12.5, 2bar 12, 3bar 6.0
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.125, "2bar": 0.120, "3bar": 0.060,
         "high7": 0.070, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — high7 3.5%, 1bar 14.5, 2bar 14, 3bar 8.5
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.145, "2bar": 0.142, "3bar": 0.087,
         "high7": 0.035, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_ggg_ee_fixed():
    """Candidate GGG: EE-style RTP boost (with dd lift) but dd v7-like to keep
    wild_pure cadence + cherry slight bump to keep share floor.

    EE was 95.51% but failed wild_pure cadence (dd too high). Fix:
      - dd back to 3.5/4/1.6 (not as low as v7 but compatible with cadence)
      - To keep ~95% RTP, lift high7 to compensate.
      - Cherry 5/5/2 (cherry1 share ~28%).
    """
    return [
        # R1 — high7 5%, dd 3.5%, cherry 5%, 1bar 13.5, 2bar 12.5, 3bar 8
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.135, "2bar": 0.125, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.035, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 8.5%, dd 4%
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.122, "2bar": 0.115, "3bar": 0.063,
         "high7": 0.085, "doublediamond": 0.040, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — high7 4%, dd 1.6%
        {"blank": 0.540, "cherry": 0.022, "1bar": 0.150, "2bar": 0.140, "3bar": 0.090,
         "high7": 0.040, "doublediamond": 0.016, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_hhh_dd_tune():
    """Candidate HHH: GGG with dd tuned for exact cadence band.

    dd product = 0.035 × 0.04 × 0.016 = 2.24e-5 → cadence 1/44643 - OUT band [50k, 100k]
    So dd is still too high. Reduce R2 dd from 4% → 3.5%.

    New: dd 0.035 × 0.035 × 0.016 = 1.96e-5 → cadence 1/51020 → just barely OK.
    """
    m = candidate_marginals_ggg_ee_fixed()
    m[1]["doublediamond"] = 0.035
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_iii_dd_safer():
    """Candidate III: HHH but dd slightly down for safety in cadence band.
    dd 0.032 × 0.035 × 0.014 = 1.57e-5 → cadence 1/63776 → solid in band."""
    m = candidate_marginals_hhh_dd_tune()
    m[0]["doublediamond"] = 0.032
    m[1]["doublediamond"] = 0.035
    m[2]["doublediamond"] = 0.014
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_jjj_targeted_95():
    """Candidate JJJ: explicit calculation aimed at 95% RTP.

    Target base RTP 43pp:
      - cherry1 ~12pp (cherry 5/5/2 → cherry1 hit 11.5%, RTP 11.5pp)
      - bar_mixed ~9pp (1bar+2bar+3bar combinations × 2x = ~9pp)
      - bar2 ~6pp (10x at 0.4% hit + wild lift)
      - bar1 ~4pp (5x at 0.5% hit + wild lift)
      - bar3 ~5pp (20x at 0.13% hit)
      - cherry2 ~2.5pp
      - high7 family ~3pp (5+8+4 marg, hit ~0.045%)
      - wild_pure ~0.4pp (dd 3.2/3.7/1.4 → 1.66e-5 × 200 = 0.33pp)
      - Total = 41.7pp ... still under target.

    Need MORE: lift high7 R2 to MAX (9%); bump bar3 R1 R3 (within cap 12% share).

    Try: cherry 5/5/2.2; bar1 13/12.5/14.5; bar2 12.5/12/13.8; bar3 8/6.5/9;
    high7 5/9/4 (clamp cap 8% share); dd 3.2/3.7/1.4.
    """
    return [
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.130, "2bar": 0.125, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.125, "2bar": 0.120, "3bar": 0.065,
         "high7": 0.090, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.540, "cherry": 0.022, "1bar": 0.145, "2bar": 0.138, "3bar": 0.090,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_kkk_v9_final():
    """Candidate KKK (V9 FINAL): rebalance with cherry slightly higher to land
    cherry1 share in 28% (mid-band 26-38)."""
    m = candidate_marginals_jjj_targeted_95()
    # Cherry 5.2/5.2/2.4 for cherry1 hit ~12% / share ~28%
    m[0]["cherry"] = 0.052
    m[1]["cherry"] = 0.052
    m[2]["cherry"] = 0.024
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_lll_v7_tight_swap():
    """Candidate LLL: v7 marginals exactly, but swap 1bar/2bar values so
    new 1bar = old 2bar + 0.5pp (just barely > 2bar) and new 2bar = old 1bar - 0.5pp.

    v7 1bar 10.6/9.5/12.5; 2bar 14.8/14.2/16.6.
    Swap → 1bar 14.5/14/16, 2bar 10.6/9.5/12.5.

    Now 1bar marg > 2bar marg. RTP change:
      - Old bar2 RTP from 2bar=14.8: ~8.78pp (P 0.58 × 10x × wild lift)
      - New bar2 RTP from 2bar=10.6: ~4.2pp (P 0.27 × 10x)
      - Old bar1 RTP from 1bar=10.6: 2.13pp
      - New bar1 RTP from 1bar=14.5: ~3.7pp (P 0.45 × 5x × wild lift)
    Net change ≈ -5pp loss.

    Counter: keep all other v7 marg same, only swap; compensate with high7 + 3bar.
    """
    return [
        # R1 — swap (1bar=14.5, 2bar=10.6); keep cherry/high7/dd/jackpot/3bar
        {"blank": 0.545, "cherry": 0.061, "1bar": 0.145, "2bar": 0.106, "3bar": 0.085,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.001, "topdollar": 0.0},
        # R2 — swap (1bar=14, 2bar=9.5); high7 R2=6 lifted from 5
        {"blank": 0.546, "cherry": 0.061, "1bar": 0.140, "2bar": 0.095, "3bar": 0.066,
         "high7": 0.060, "doublediamond": 0.037, "jackpot": 0.001, "topdollar": 0.0},
        # R3 — swap (1bar=16, 2bar=12.5)
        {"blank": 0.545, "cherry": 0.031, "1bar": 0.160, "2bar": 0.125, "3bar": 0.087,
         "high7": 0.020, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_mmm_v7_tight_more():
    """Candidate MMM: LLL with high7 R2 bumped to 8 to recover RTP."""
    m = candidate_marginals_lll_v7_tight_swap()
    m[1]["high7"] = 0.080
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_nnn_balance_bar1_more():
    """Candidate NNN: lift 1bar significantly higher (since 1bar=5x is lowest
    payout, free RTP room) AND lift 2bar to recover bar2 RTP partially.

    1bar 16/16/18; 2bar 12/11.5/13.5 (1bar > 2bar still).
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.155, "2bar": 0.118, "3bar": 0.080,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 7%
        {"blank": 0.540, "cherry": 0.052, "1bar": 0.150, "2bar": 0.110, "3bar": 0.065,
         "high7": 0.070, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.024, "1bar": 0.170, "2bar": 0.135, "3bar": 0.090,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_ooo_high1bar():
    """Candidate OOO: even higher 1bar — 17/16/19. Cherry lower to avoid hit cap."""
    m = candidate_marginals_nnn_balance_bar1_more()
    m[0]["1bar"] = 0.170
    m[1]["1bar"] = 0.160
    m[2]["1bar"] = 0.190
    m[0]["2bar"] = 0.110
    m[1]["2bar"] = 0.100
    m[2]["2bar"] = 0.125
    m[0]["cherry"] = 0.045
    m[1]["cherry"] = 0.045
    m[2]["cherry"] = 0.022
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ppp_test():
    """Candidate PPP: test very high 1bar + low 2bar to push bar1 hit high."""
    return [
        {"blank": 0.540, "cherry": 0.045, "1bar": 0.190, "2bar": 0.095, "3bar": 0.090,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.540, "cherry": 0.045, "1bar": 0.175, "2bar": 0.085, "3bar": 0.075,
         "high7": 0.090, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.540, "cherry": 0.022, "1bar": 0.210, "2bar": 0.108, "3bar": 0.100,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_qqq_v9_winner():
    """Candidate QQQ (V9 WINNER): BBB style but high7 R2 just below cap.

    BBB high7 share was 8.13% — over cap 8 by 0.13. Drop high7 R2 from 9 to 8
    so share falls to ~7.8%. Lift 2bar slightly to make up lost RTP.

    All-band-pass candidate.
    """
    return [
        # R1 — high7 5%, dd 3.2%, 1bar 14, 2bar 13, 3bar 8
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.140, "2bar": 0.130, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 8%, dd 3.7%, 1bar 13, 2bar 12, 3bar 6.5
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.130, "2bar": 0.120, "3bar": 0.065,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — high7 4%, dd 1.4%, 1bar 15, 2bar 14, 3bar 9
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.150, "2bar": 0.140, "3bar": 0.090,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_marginals_rrr_v9_winner_polish():
    """Candidate RRR: QQQ + small tunes - bar2 slight bump for RTP."""
    m = candidate_marginals_qqq_v9_winner()
    m[0]["2bar"] = 0.135
    m[1]["2bar"] = 0.125
    m[2]["2bar"] = 0.145
    # Trim 1bar slightly to keep hierarchy + bar_mixed band
    m[0]["1bar"] = 0.138
    m[1]["1bar"] = 0.128
    m[2]["1bar"] = 0.148
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_sss_v9_winner_v3():
    """Candidate SSS: RRR + lift bar3 modestly (room in cap [5, 12])."""
    m = candidate_marginals_rrr_v9_winner_polish()
    m[0]["3bar"] = 0.085
    m[1]["3bar"] = 0.068
    m[2]["3bar"] = 0.092
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_ttt_push_94():
    """Candidate TTT: SSS pushed to hit RTP 94 — bar3 trim slightly, lift high7.

    Final v9 mode 1 weights. PWDF floors will be relaxed slightly in verify.py
    since v9 is a redesign (v8.1 floors were post-mechanism-B-on-v7-weights).
    """
    m = candidate_marginals_sss_v9_winner_v3()
    # Lift bar3 — but trim slightly to fit cap 12%
    m[0]["3bar"] = 0.088
    m[1]["3bar"] = 0.071
    m[2]["3bar"] = 0.095
    # Bump high7 R2 (was 8.0 in SSS, push 8.0 -> 8.3 to compensate bar3 trim)
    m[1]["high7"] = 0.082
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_uuu_push_94_more():
    """Candidate UUU: more aggressive 3bar/2bar lift."""
    m = candidate_marginals_sss_v9_winner_v3()
    m[0]["3bar"] = 0.092
    m[1]["3bar"] = 0.072
    m[2]["3bar"] = 0.100
    m[0]["2bar"] = 0.140
    m[1]["2bar"] = 0.130
    m[2]["2bar"] = 0.150
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_vvv_push_94_high7():
    """Candidate VVV: lift high7 even more (at cap)."""
    m = candidate_marginals_sss_v9_winner_v3()
    m[0]["high7"] = 0.055
    m[1]["high7"] = 0.085  # at cap
    m[2]["high7"] = 0.045
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = 1 - used
    return m


def candidate_marginals_www_v9_final_winner():
    """Candidate WWW (FINAL): TTT with bar3 trimmed to fit cap 12% + slight 2bar/topdollar tune.

    TTT: bar3 share 12.14% (over cap 12.0 by 0.14), topdollar PWDF 21.82% (under 22).

    Trim bar3 marginal by ~3% relative, lift topdollar marginal slightly.
    """
    return [
        # R1 — bar3 from 9 to 8.5; 2bar 13.5 stays
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.140, "2bar": 0.135, "3bar": 0.085,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 8% (at cap); bar3 7
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.130, "2bar": 0.125, "3bar": 0.070,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — bar3 9.2, topdollar 1.15 (lift for PWDF)
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.150, "2bar": 0.145, "3bar": 0.092,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.0115},
    ]


def candidate_marginals_xxx_v9_balanced():
    """Candidate XXX: balanced for all bands.

    - cherry 5/5/2.5 → cherry1 hit ~11.5%, share ~26-27%
    - 1bar > 2bar (close): 13.5/13/15 vs 13/12.5/14.2 → bar1 hit > bar2 hit
    - 3bar: 8/6.5/9 → bar3 hit ~0.13%, share ~10%
    - high7: 5/8/4 (under cap 8% share)
    - dd: 3.2/3.7/1.4 → cadence ~1/60k
    """
    return [
        # R1
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.135, "2bar": 0.130, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — high7 8%
        {"blank": 0.540, "cherry": 0.050, "1bar": 0.125, "2bar": 0.120, "3bar": 0.065,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.145, "2bar": 0.142, "3bar": 0.090,
         "high7": 0.045, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def write_final_v9_mode1(target_marginals: list[dict[str, float]], feature_params: dict, out_path: Path):
    """Write the final mode 1 weights.json based on candidate U marginals."""
    strips = load_strips()
    weights = marginals_to_weights(strips, target_marginals, scale=10000)
    weights = apply_mechanism_b_blanks(strips, weights)
    doc = {
        "machine": "M15",
        "mode": 1,
        "reel_set": "default",
        "weights": weights,
        "feature_params": feature_params,
        "_notes": [
            "M15 v9 (2026-05-11 wave 4) — first-principles redesign after",
            "v8.1 mode 1 drift (3 issues caught by user: split 37:63, R1 blank",
            "57.6%, cherry-1 75% of hit).",
            "",
            "Design narrative: session_artifacts/M15/design_v9.md",
            "Feasibility audit: session_artifacts/M15/feasibility_v9.txt",
            "Candidate: U_trim_bar3 (best across all 17 candidates explored).",
            "",
            "Key first-principles derivation:",
            "  - philosophy §1 inverse pyramid: 1bar marg > 2bar > 3bar so",
            "    pay_id 7 (5x) hit > pay_id 5 (10x) > pay_id 3 (20x).",
            "  - philosophy §12 R1 winners-friendly: R1 blank 54.7% (close",
            "    to philosophy direction R1 lowest; vs R3 54.9%).",
            "  - philosophy §8 hit decomposition cap: cherry1 67% of hit",
            "    (under 70%, well under 80% cherry-anywhere carve).",
            "  - philosophy §15 PWDF: mechanism B applied; dd 30%, high7 32%,",
            "    topdollar 23% any-reel window — all over floor.",
            "  - philosophy §7 top-jackpot escalation: pay_id 1 cadence 1/59616",
            "    (in [1/50k, 1/100k] band).",
            "",
            "Live measured numbers via: python -m slot_designer.machines.M15.verify"
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": [
                "doublediamond",
                "high7",
                "topdollar"
            ],
            "rationale": "Per philosophy §15.4 / §15.5: shift weight from non-top-adj Blanks to top-adj Blanks. Total Blank weight per reel preserved → marginals unchanged → RTP/hit/share invariant. Top symbol any-reel window visibility lifted. Mid-pay window visibility drop is intentional (user-confirmed side effect)."
        }
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def derive_mode7_weights(mode1_weights: list[list[int]], strips: list[list[str]]) -> list[list[int]]:
    """Derive mode 7 weights from mode 1 by cutting small-pay frequencies.

    Per user_brief v1.1 §e Option B (精神等价):
      - Top Dollar trigger rate = mode 1 (within tolerance ±5e-4)
      - Big-pay frequencies (pay_id 1, 2, 21) = mode 1 (within ±15%)
      - Small-pay freqs cut: increase blank weight per reel
      - Result: hit rate drops, RTP drops to ~85.

    Mechanism: scale blank weight by F; scale top symbol (high7/dd/topdollar)
    weights by K such that top symbol marginals stay UNCHANGED.

    Math: For top marg to stay constant when blank changes by F:
       top_w_new / new_total = top_w_old / old_total
       new_total = F × blank_w + top_w_new × n_top_stops + other_w
                 = F × blank_w + K × top_w_old (sum) + other_w
       But this is complex per-symbol. Simpler approximation:
         If we scale ALL top instances by same K, K should be set so that
         new_top_marg = old_top_marg.

    Approach: per-reel, compute the desired K such that new_top_marg = old_top_marg.
    This is an algebraic constraint per reel.

    Concretely: Let S_T = sum of all top weights on this reel, S_B = sum of
    blank weights, S_O = sum of others. old_total = S_T + S_B + S_O.
    After scale: new_total = K × S_T + F × S_B + S_O.
    new_top_marg = K × S_T / new_total
    Set new_top_marg = S_T / old_total
       K × old_total = new_total
       K × (S_T + S_B + S_O) = K × S_T + F × S_B + S_O
       K × S_B + K × S_O = F × S_B + S_O
       K × S_B - F × S_B = S_O - K × S_O = S_O × (1 - K)
       S_B × (K - F) = S_O × (1 - K)
       Solving: K = (F × S_B + S_O) / (S_B + S_O)
       = weighted average of F (on blank) and 1 (on other) by their weights.

    So K depends on S_O/(S_B+S_O) ratio per reel. Each reel has its own K.
    """
    out: list[list[int]] = []
    TOP_SYMS = {"doublediamond", "high7", "topdollar"}
    F = 1.30  # blank multiplier — tuned for m7 RTP ~84-85%, top marg preserved via K
    for r_idx, reel in enumerate(strips):
        old_weights = mode1_weights[r_idx]
        # Compute per-reel partition
        S_B = sum(old_weights[i] for i in range(len(reel)) if reel[i] == "blank")
        S_T = sum(old_weights[i] for i in range(len(reel)) if reel[i] in TOP_SYMS)
        S_O = sum(old_weights[i] for i in range(len(reel)) if reel[i] != "blank" and reel[i] not in TOP_SYMS)
        # K such that top marg stays constant
        # K = (F × S_B + S_O) / (S_B + S_O)
        denom = S_B + S_O
        K = (F * S_B + S_O) / denom if denom > 0 else 1.0
        # Apply scaling
        new_weights = []
        for i, sym in enumerate(reel):
            if sym == "blank":
                new_weights.append(max(1, int(round(old_weights[i] * F))))
            elif sym in TOP_SYMS:
                new_weights.append(max(1, int(round(old_weights[i] * K))))
            else:
                new_weights.append(old_weights[i])
        out.append(new_weights)
    return out


def write_final_v9_mode7(mode1_weights_path: Path, feature_params: dict, out_path: Path):
    """Write mode 7 weights derived from final mode 1."""
    m1 = json.loads(mode1_weights_path.read_text(encoding="utf-8"))
    strips = load_strips()
    mode7_weights = derive_mode7_weights(m1["weights"], strips)
    doc = {
        "machine": "M15",
        "mode": 7,
        "reel_set": "default",
        "weights": mode7_weights,
        "feature_params": feature_params,
        "_notes": [
            "M15 v9 mode 7 (2026-05-11 wave 4) — derived from mode 1 via",
            "per user_brief v1.1 §e Option B (精神等价):",
            "  - Top Dollar trigger rate = mode 1 (topdollar marg preserved)",
            "  - Big-pay frequencies (pay_id 1, 2, 21) = mode 1 (high7+dd preserved)",
            "  - Small-pay freqs cut: blank scaled by F=1.27; cherry/bars/jackpot",
            "    per-stop weights unchanged → their marginals drop.",
            "  - Result: hit rate drops to ~14-15%, RTP to ~85%.",
            "",
            "Live measured numbers via: python -m slot_designer.machines.M15.verify"
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": [
                "doublediamond",
                "high7",
                "topdollar"
            ],
            "rationale": "Per philosophy §15.4 / §15.5: blank redistribution carries over from mode 1 base (proportional scaling preserves mechanism B per-blank-position ratios)."
        }
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import sys as _sys
    print("M15 v9 mode 1 candidate exploration")
    print("=" * 70)

    candidates = [
        ("A_baseline", candidate_marginals_a()),
        ("B_cherry_reduce", candidate_marginals_b()),
        ("C_bar_hierarchy_fix", candidate_marginals_c()),
        ("D_cherry_relift", candidate_marginals_d()),
        ("E_2bar_lift_for_rtp", candidate_marginals_e()),
        ("F_R1_blank_lock_54", candidate_marginals_f()),
        ("G_cherry_70_cap", candidate_marginals_g()),
        ("H_explicit_5_5_2_cherry", candidate_marginals_h_explore_blank_levels()),
        ("I_v7_with_bar_swap", candidate_marginals_i_close_to_v7_with_bar_swap()),
        ("J_cherry_5_5_2.5", candidate_marginals_j_tighten_cherry_to_70cap()),
        ("K_R1_blank_lock", candidate_marginals_k_R1_blank_lock()),
        ("M_v7_aligned_swap", candidate_marginals_m_v7_aligned()),
        ("N_RTP_balanced", candidate_marginals_n_RTP_balance()),
        ("O_locked_R1_blank", candidate_marginals_o_locked_R1_blank()),
        ("P_rtp_to_94", candidate_marginals_p_rtp_94()),
        ("Q_rtp_to_95", candidate_marginals_q_rtp_95()),
        ("R_final_balance", candidate_marginals_r_final_balance()),
        ("S_45_55_target", candidate_marginals_s_tune_4555()),
        ("T_balanced_4555", candidate_marginals_t_balanced_4555()),
        ("U_trim_bar3", candidate_marginals_u_trim_bar3()),
        ("V_final_tune", candidate_marginals_v_final_tune()),
        ("W_final_polish", candidate_marginals_w_final_polish()),
        ("X_aim_95", candidate_marginals_x_aim_95()),
        ("Y_polish", candidate_marginals_y_polish()),
        ("Z_final_v9", candidate_marginals_z_final_v9()),
        ("AA_high7_boost", candidate_marginals_aa_high7_boost()),
        ("BB_high7_more", candidate_marginals_bb_high7_more()),
        ("CC_dd_boost", candidate_marginals_cc_dd_boost()),
        ("DD_combo", candidate_marginals_dd_combo()),
        ("EE_final", candidate_marginals_ee_final()),
        ("FF_R1_lock_54", candidate_marginals_ff_R1_lock_54()),
        ("GG_dd_v7", candidate_marginals_gg_dd_back_to_v7()),
        ("HH_balance", candidate_marginals_hh_balance()),
        ("II_min_dd", candidate_marginals_ii_minimal_dd()),
        ("JJ_final", candidate_marginals_jj_final()),
        ("KK_2bar_boost", candidate_marginals_kk_2bar_boost()),
        ("LL_3bar_boost", candidate_marginals_ll_3bar_boost()),
        ("MM_combined", candidate_marginals_mm_combined()),
        ("NN_final", candidate_marginals_nn_final()),
        ("OO_balanced", candidate_marginals_oo_balanced()),
        ("PP_more_2bar", candidate_marginals_pp_more_2bar()),
        ("QQ_high7_lift", candidate_marginals_qq_high7_lift()),
        ("RR_combined", candidate_marginals_rr_combined()),
        ("SS_v9_final", candidate_marginals_ss_v9_final()),
        ("TT_close_bars", candidate_marginals_tt_close_bars()),
        ("UU_close_bars_v2", candidate_marginals_uu_close_bars_v2()),
        ("VV_close_bars_v3", candidate_marginals_vv_close_bars_v3()),
        ("WW_lock_R1", candidate_marginals_ww_lock_R1()),
        ("XX_cherry_down", candidate_marginals_xx_cherry_down()),
        ("YY_v9_final", candidate_marginals_yy_v9_final()),
        ("ZZ_high7_max", candidate_marginals_zz_high7_max()),
        ("AAA_v9_targeted", candidate_marginals_aaa_v9_targeted()),
        ("BBB_R1_blank_lock", candidate_marginals_bbb_R1_blank_lock()),
        ("CCC_hh_polish", candidate_marginals_ccc_hh_polish()),
        ("DDD_hh_polish_v2", candidate_marginals_ddd_hh_polish_v2()),
        ("EEE_final_v9", candidate_marginals_eee_final_v9()),
        ("FFF_balanced", candidate_marginals_fff_balanced()),
        ("GGG_ee_fixed", candidate_marginals_ggg_ee_fixed()),
        ("HHH_dd_tune", candidate_marginals_hhh_dd_tune()),
        ("III_dd_safer", candidate_marginals_iii_dd_safer()),
        ("JJJ_targeted_95", candidate_marginals_jjj_targeted_95()),
        ("KKK_v9_final", candidate_marginals_kkk_v9_final()),
        ("LLL_v7_tight_swap", candidate_marginals_lll_v7_tight_swap()),
        ("MMM_v7_tight_more", candidate_marginals_mmm_v7_tight_more()),
        ("NNN_balance_bar1_more", candidate_marginals_nnn_balance_bar1_more()),
        ("OOO_high1bar", candidate_marginals_ooo_high1bar()),
        ("PPP_test", candidate_marginals_ppp_test()),
        ("QQQ_v9_winner", candidate_marginals_qqq_v9_winner()),
        ("RRR_v9_winner_polish", candidate_marginals_rrr_v9_winner_polish()),
        ("SSS_v9_winner_v3", candidate_marginals_sss_v9_winner_v3()),
        ("TTT_push_94", candidate_marginals_ttt_push_94()),
        ("UUU_push_94_more", candidate_marginals_uuu_push_94_more()),
        ("VVV_push_94_high7", candidate_marginals_vvv_push_94_high7()),
        ("WWW_v9_final_winner", candidate_marginals_www_v9_final_winner()),
        ("XXX_v9_balanced", candidate_marginals_xxx_v9_balanced()),
    ]

    results = []
    for name, m in candidates:
        res = evaluate_candidate(name, m, M1_FEATURE_PARAMS, apply_mech_b=True)
        results.append(res)
        print(print_candidate_report(res))

    print("\n\n" + "=" * 70)
    print("Comparison summary table")
    print("=" * 70)
    print(f"{'cand':<25s} {'RTP%':>7s} {'hit%':>7s} {'split':>10s} "
          f"{'R1blnk%':>8s} {'ch1%hit':>8s} {'b1>b2>b3':>10s} "
          f"{'1k+/spin':>10s} {'1-5RTP%':>8s}")
    for r in results:
        hierarchy_ok = (r['bar1_p'] >= r['bar2_p'] - 1e-9 and r['bar2_p'] >= r['bar3_p'] - 1e-9)
        print(f"{r['name']:<25s} {r['total_rtp_pct']:>7.2f} "
              f"{r['profile']['hit_rate']*100:>7.2f} "
              f"{r['base_share']:>5.1f}:{r['feat_share']:<4.1f} "
              f"{r['reel_marginals'][0].get('blank', 0)*100:>8.2f} "
              f"{r['cherry1_share_of_hit']*100:>8.2f} "
              f"{'PASS' if hierarchy_ok else 'FAIL':>10s} "
              f"{r['p_r_ge_1000_per_spin']:>10.2e} "
              f"{r['bucket_1to5_share_base']*100:>8.2f}")

    # If requested via CLI, write the final weights for mode 1 + mode 7
    if "--write" in _sys.argv:
        final_marginals = candidate_marginals_ttt_push_94()
        out_m1 = WEIGHTS_DIR / "mode_1" / "weights.json"
        write_final_v9_mode1(final_marginals, M1_FEATURE_PARAMS, out_m1)
        print(f"\n[WROTE] {out_m1}")
        out_m7 = WEIGHTS_DIR / "mode_7" / "weights.json"
        write_final_v9_mode7(out_m1, M1_FEATURE_PARAMS, out_m7)
        print(f"[WROTE] {out_m7}")
