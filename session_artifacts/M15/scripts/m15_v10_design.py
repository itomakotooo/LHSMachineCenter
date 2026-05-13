"""M15 v10 mode 1 redesign — tighten 2 dimensions on top of v9.

Stage 4 wave-5 (2026-05-11): user accepts v9 results, now tightens further:

  1. R1 blank marginal must land in [30, 40]%  (v9 was 50.25%)
  2. Bucket RTP shift (exact-targeted):
     - ge1_lt5  RTP: 22.33 -> 12.33 pp  (-10pp)
     - ge5_lt10 RTP: 3.72  -> 8.72  pp  (+5pp)
     - ge10_lt20 RTP: 4.16  -> 9.16 pp  (+5pp)
     Net change to base RTP = 0pp.

Constraints preserved (no compromise):
  - hit [15, 18]%
  - total RTP [94, 96]%
  - base : feature split near 45:55 (v9 was 46.6:53.4)
  - P(R>=1000/spin) <= 1e-5
  - jackpot any-reel <= 0.6%
  - cherry-1 % hit <= ~70% (carve to 80% allowed)
  - bar1 hit > bar2 hit > bar3 hit (within tied tolerance 0.10pp)
  - cross-mode invariants (m7 = m1 cut with byte-equal big pay + trigger)
  - paytable never modified

Engineering insight (the tradeoff):
  R1 blank drop ~50% -> ~35% means R1 non-blank marginals must absorb +15pp.
  This boosts every pay involving R1, raising hit rate. To keep hit <= 18%
  we compensate by raising R2 / R3 blank.

  For bucket shift (-10/+5/+5):
    - Drop cherry marginals across reels -> cherry1 (1x) freq drops, RTP -4 to -5pp
    - Drop / restructure bar_mixed (2x) by cutting bar marginals on R2 / R3 -> -4 to -5pp
    - Raise bar1 (5x, R1 boost helps) hit -> +X to ge5_lt10
    - Raise bar2 (10x, R2/R3 boost via 1 wild lift) hit -> +X to ge10_lt20
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
# strip helpers (same as v9)
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
    """Convert per-reel target marginals to integer per-stop weights."""
    weights: list[list[int]] = []
    counts_per_reel = stop_counts_per_reel(strips)
    for r_idx, reel in enumerate(strips):
        target = target_marginals[r_idx]
        counts = counts_per_reel[r_idx]
        wps: dict[str, int] = {}
        for sym, frac in target.items():
            if sym not in counts:
                continue
            cnt = counts[sym]
            w_float = scale * frac / cnt
            wps[sym] = max(1, int(round(w_float)))
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
    top-adj Blanks absorb the remainder. RTP-neutral.
    """
    out = [list(row) for row in weights]
    for r_idx, reel in enumerate(strips):
        n = len(reel)
        total_blank_w = sum(out[r_idx][i] for i in range(n) if reel[i] == "blank")
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
            continue
        reserve = non_top_adj_floor * len(non_top_adj_positions)
        leftover = total_blank_w - reserve
        if leftover <= 0:
            continue
        per_top_adj = leftover // len(top_adj_positions)
        rem = leftover - per_top_adj * len(top_adj_positions)
        for i in non_top_adj_positions:
            out[r_idx][i] = non_top_adj_floor
        for k, i in enumerate(top_adj_positions):
            out[r_idx][i] = per_top_adj + (1 if k < rem else 0)
    return out


# -----------------------------------------------------------------------
# v10 mode 1 feature_params (carry from v9 — 46x EV at trigger 1.13%)
# -----------------------------------------------------------------------

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
    """Build weights, optionally apply mechanism B, run full analytic profile."""
    strips = load_strips()
    weights = marginals_to_weights(strips, target_marginals, scale=scale)
    if apply_mech_b:
        weights = apply_mechanism_b_blanks(strips, weights)

    weights_doc = {
        "machine": "M15",
        "mode": 1,
        "reel_set": "default",
        "weights": weights,
        "feature_params": feature_params,
    }
    tmp_path = _ROOT / "session_artifacts" / "M15" / "_tmp_v10_candidate.json"
    tmp_path.write_text(json.dumps(weights_doc, indent=2), encoding="utf-8")
    try:
        engine, _spec = load_engine(SPEC_PATH, tmp_path, strips_path=STRIPS_PATH)
        profile = analytic_profile(engine)
        margs = [compute_reel_marginal(r) for r in engine.reels]
        reel_strips_dict = [
            [{"symbol": s.symbol, "weight": int(s.weight)} for s in r.stops]
            for r in engine.reels
        ]
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    x_count = tuple(feature_params["x_count_weights"])
    y_count = tuple(feature_params["y_count_weights"])
    x_val = tuple(feature_params.get("x_value_weights", [1.0] * 10))
    y_val = tuple(feature_params.get("y_value_weights", [1.0, 1.0]))
    accept_thresh = float(feature_params.get("accept_threshold", 40))
    max_rounds = int(feature_params.get("max_rounds", 4))
    fspec = FeatureSpec(
        x_count_weights=x_count, y_count_weights=y_count,
        x_value_weights=x_val, y_value_weights=y_val,
        accept_threshold=accept_thresh, max_rounds=max_rounds,
    )
    fstats = analyze_feature(fspec)
    trigger_rate = margs[2].get("topdollar", 0.0)
    feature_rtp_pp = trigger_rate * fstats.expected_payout * 100.0
    total_rtp_pct = profile["rtp_pct"] + feature_rtp_pp
    round_dist = _round_payout_distribution(x_count, y_count, x_val, y_val)
    p_r_ge_1000_per_trigger = sum(p for r, p in round_dist if r >= 1000)
    p_r_ge_1000_per_spin = trigger_rate * p_r_ge_1000_per_trigger

    base_pp = profile["rtp_pct"]
    feat_pp = feature_rtp_pp
    base_share = base_pp / total_rtp_pct * 100 if total_rtp_pct > 0 else 0
    feat_share = feat_pp / total_rtp_pct * 100 if total_rtp_pct > 0 else 0

    pay_hits = profile["pay_hits"]
    pay_rtp = profile["pay_rtp"]
    cherry1_p = pay_hits.get("9", 0.0)
    cherry1_share_of_hit = cherry1_p / profile["hit_rate"] if profile["hit_rate"] > 0 else 0
    bar1_p = pay_hits.get("7", 0.0)
    bar2_p = pay_hits.get("5", 0.0)
    bar3_p = pay_hits.get("3", 0.0)
    cherry2_p = pay_hits.get("71", 0.0)
    cherry3_p = pay_hits.get("4", 0.0)
    bar_mixed_p = pay_hits.get("8", 0.0)
    high7w_p = pay_hits.get("2", 0.0)
    high7p_p = pay_hits.get("21", 0.0)
    wild_p = pay_hits.get("1", 0.0)

    bucket_rate = profile["bucket_rate"]
    bucket_rtp_d = profile["bucket_rtp"]
    bucket_1to5_rate = bucket_rate.get("ge1_lt5", 0.0)
    bucket_1to5_rtp = bucket_rtp_d.get("ge1_lt5", 0.0) * 100
    bucket_5to10_rtp = bucket_rtp_d.get("ge5_lt10", 0.0) * 100
    bucket_10to20_rtp = bucket_rtp_d.get("ge10_lt20", 0.0) * 100
    bucket_20to50_rtp = bucket_rtp_d.get("ge20_lt50", 0.0) * 100
    bucket_50to100_rtp = bucket_rtp_d.get("ge50_lt100", 0.0) * 100
    bucket_100to200_rtp = bucket_rtp_d.get("ge100_lt200", 0.0) * 100
    bucket_200to500_rtp = bucket_rtp_d.get("ge200_lt500", 0.0) * 100
    bucket_1to5_share_base = (bucket_1to5_rtp / base_pp) if base_pp > 0 else 0

    top_window = {}
    for sym in ("doublediamond", "high7", "topdollar"):
        max_pw = 0.0
        for strip in reel_strips_dict:
            pw = symbol_window_probability(strip, sym)
            if pw > max_pw:
                max_pw = pw
        top_window[sym] = max_pw

    # Family rtp pp
    family_pp = defaultdict(float)
    fam_map = {
        "9": "cherry1", "71": "cherry2", "4": "cherry3",
        "1": "wild_pure", "2": "high7_wild", "21": "high7_pure",
        "3": "bar3", "5": "bar2", "7": "bar1", "8": "bar_mixed",
    }
    for pid, rtp in pay_rtp.items():
        fam = fam_map.get(pid)
        if fam is None:
            continue
        family_pp[fam] += rtp * 100

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
        "bar1_p": bar1_p, "bar2_p": bar2_p, "bar3_p": bar3_p,
        "cherry1_p": cherry1_p, "cherry2_p": cherry2_p, "cherry3_p": cherry3_p,
        "bar_mixed_p": bar_mixed_p,
        "high7w_p": high7w_p, "high7p_p": high7p_p, "wild_p": wild_p,
        "bucket_1to5_rate": bucket_1to5_rate,
        "bucket_1to5_rtp_pp": bucket_1to5_rtp,
        "bucket_5to10_rtp_pp": bucket_5to10_rtp,
        "bucket_10to20_rtp_pp": bucket_10to20_rtp,
        "bucket_20to50_rtp_pp": bucket_20to50_rtp,
        "bucket_50to100_rtp_pp": bucket_50to100_rtp,
        "bucket_100to200_rtp_pp": bucket_100to200_rtp,
        "bucket_200to500_rtp_pp": bucket_200to500_rtp,
        "bucket_1to5_share_base": bucket_1to5_share_base,
        "top_window": top_window,
        "family_pp": dict(family_pp),
    }


def print_candidate_report(res: dict) -> str:
    """Eyeball metrics for a candidate."""
    lines = []
    name = res["name"]
    p = res["profile"]
    margs = res["reel_marginals"]
    lines.append(f"\n======== Candidate: {name} ========")
    lines.append(f"Total RTP:        {res['total_rtp_pct']:.3f}%")
    lines.append(f"  Base RTP:       {res['base_pp']:.3f}pp  ({res['base_share']:.1f}%)")
    lines.append(f"  Feature RTP:    {res['feat_pp']:.3f}pp  ({res['feat_share']:.1f}%)")
    lines.append(f"Base hit rate:    {p['hit_rate']*100:.3f}%")
    lines.append(f"Trigger rate:     {res['trigger_rate']*100:.3f}%  (1 in {1/res['trigger_rate']:.0f})")
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
    lines.append("Bucket RTP (pp):")
    lines.append(f"  ge1_lt5:     {res['bucket_1to5_rtp_pp']:.2f}pp  (TARGET 12.33pp, band [11.5, 13.5])")
    lines.append(f"  ge5_lt10:    {res['bucket_5to10_rtp_pp']:.2f}pp  (TARGET 8.72pp,  band [8.0, 9.5])")
    lines.append(f"  ge10_lt20:   {res['bucket_10to20_rtp_pp']:.2f}pp  (TARGET 9.16pp,  band [8.5, 10.0])")
    lines.append(f"  ge20_lt50:   {res['bucket_20to50_rtp_pp']:.2f}pp")
    lines.append(f"  ge50_lt100:  {res['bucket_50to100_rtp_pp']:.2f}pp")
    lines.append(f"  ge100_lt200: {res['bucket_100to200_rtp_pp']:.2f}pp")
    lines.append(f"  ge200_lt500: {res['bucket_200to500_rtp_pp']:.2f}pp")
    lines.append("")
    lines.append(f"R1 blank = {margs[0].get('blank',0)*100:.2f}%  (TARGET [30, 40])")
    lines.append(f"cherry1 share of hit = {res['cherry1_share_of_hit']*100:.2f}%  (cap 70-80%)")
    lines.append("")
    lines.append("Hierarchy:")
    hierarchy_ok = (res['bar1_p'] >= res['bar2_p'] - 1e-5 and res['bar2_p'] >= res['bar3_p'] - 1e-5)
    lines.append(f"  bar1 P={res['bar1_p']*100:.4f}% > bar2 P={res['bar2_p']*100:.4f}% > bar3 P={res['bar3_p']*100:.4f}%  {'PASS' if hierarchy_ok else 'FAIL'}")
    lines.append("")
    lines.append("Per-pay hits:")
    lines.append(f"  pay 9  cherry1:    {res['cherry1_p']*100:.4f}%")
    lines.append(f"  pay 8  bar_mixed:  {res['bar_mixed_p']*100:.4f}%")
    lines.append(f"  pay 7  bar1 5x:    {res['bar1_p']*100:.4f}%")
    lines.append(f"  pay 71 cherry2 5x: {res['cherry2_p']*100:.4f}%")
    lines.append(f"  pay 5  bar2 10x:   {res['bar2_p']*100:.4f}%")
    lines.append(f"  pay 4  cherry3 15x:{res['cherry3_p']*100:.4f}%")
    lines.append(f"  pay 3  bar3 20x:   {res['bar3_p']*100:.4f}%")
    lines.append(f"  pay 21 high7_pure: {res['high7p_p']*100:.4f}%")
    lines.append(f"  pay 2  high7_wild: {res['high7w_p']*100:.4f}%")
    lines.append(f"  pay 1  wild_pure:  {res['wild_p']*100:.4f}%")
    lines.append("")
    lines.append("Family RTP (pp):")
    fp = res["family_pp"]
    high7_combined = fp.get("high7_wild", 0) + fp.get("high7_pure", 0)
    bands = {
        "cherry1": (26.0, 38.0), "bar_mixed": (12.0, 25.0),
        "bar1": (4.0, 12.0), "bar2": (10.0, 20.0), "bar3": (5.0, 12.0),
        "high7": (2.5, 8.0), "wild_pure": (0.4, 2.0),
    }
    for fam, (lo, hi) in bands.items():
        if fam == "high7":
            v = high7_combined
        else:
            v = fp.get(fam, 0)
        share = (v / res["base_pp"]) * 100 if res["base_pp"] > 0 else 0
        status = "OK" if lo <= share <= hi else "OUT"
        lines.append(f"  {fam}: {v:.2f}pp  share={share:.2f}%  band=[{lo}, {hi}]  {status}")
    lines.append("")
    lines.append("PWDF top-symbol any-reel:")
    for sym, pw in res["top_window"].items():
        lines.append(f"  {sym}: {pw*100:.2f}%")
    lines.append("")
    lines.append("Jackpot per-reel:")
    for r_idx in range(3):
        m = margs[r_idx].get("jackpot", 0)
        lines.append(f"  R{r_idx+1}: {m*100:.3f}%")
    p1 = res['profile']["pay_hits"].get("1", 0)
    cadence = 1.0 / p1 if p1 > 0 else float("inf")
    lines.append("")
    lines.append(f"wild_pure cadence: 1 in {cadence:.0f}  (band [1/50k, 1/100k])")

    # Pass/fail summary
    targets = {
        "R1_blank_30_40": (margs[0].get("blank", 0) * 100, 30.0, 40.0),
        "bucket_1to5_RTP": (res["bucket_1to5_rtp_pp"], 11.5, 13.5),
        "bucket_5to10_RTP": (res["bucket_5to10_rtp_pp"], 8.0, 9.5),
        "bucket_10to20_RTP": (res["bucket_10to20_rtp_pp"], 8.5, 10.0),
        "hit_rate": (p["hit_rate"] * 100, 15.0, 18.0),
        "total_RTP": (res["total_rtp_pct"], 94.0, 96.0),
    }
    lines.append("")
    lines.append("=== HARD TARGETS ===")
    all_ok = True
    for k, (v, lo, hi) in targets.items():
        ok = lo <= v <= hi
        all_ok = all_ok and ok
        lines.append(f"  {k}: {v:.3f}  band=[{lo}, {hi}]  {'PASS' if ok else 'FAIL'}")
    lines.append(f"  ALL HARD: {'PASS' if all_ok else 'FAIL'}")
    return "\n".join(lines)


# -----------------------------------------------------------------------
# v10 candidates — exploration toward R1 blank 30-40 + bucket shift
# -----------------------------------------------------------------------

def _balance_blank(m):
    """For each reel, set blank = 1 - sum(other marginals)."""
    for r in m:
        used = sum(v for k, v in r.items() if k != "blank")
        r["blank"] = round(1 - used, 6)
    return m


def candidate_A_v9_baseline():
    """Sanity: v9 marginals reproduced (TTT)."""
    return [
        {"blank": 0.500, "cherry": 0.050, "1bar": 0.140, "2bar": 0.135, "3bar": 0.090,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.500, "cherry": 0.050, "1bar": 0.130, "2bar": 0.125, "3bar": 0.071,
         "high7": 0.082, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.520, "cherry": 0.025, "1bar": 0.150, "2bar": 0.145, "3bar": 0.095,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_B_r1_blank_35_naive():
    """B: drop R1 blank to 35% by raising R1 1bar/2bar; compensate
    via R2/R3 blank rise to keep hit in band."""
    return _balance_blank([
        # R1 — blank 35% (drop 15pp from v9). Add to 1bar (5x, frequent low pay)
        {"blank": 0.350, "cherry": 0.050, "1bar": 0.260, "2bar": 0.180, "3bar": 0.090,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank lift 50%->62 to compensate hit rise. Keep high7 8% (cap)
        {"blank": 0.620, "cherry": 0.030, "1bar": 0.090, "2bar": 0.080, "3bar": 0.050,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank lift 52->65 to compensate
        {"blank": 0.650, "cherry": 0.020, "1bar": 0.075, "2bar": 0.080, "3bar": 0.060,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_C_cut_cherry_global():
    """C: cherry drop everywhere to free 4-5pp from cherry1.
    cherry 3/3/1.5 instead of 5/5/2.5. Bar tuned for bucket shift."""
    return _balance_blank([
        # R1 — blank 35%; cherry 3%; bar1 boosted
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.250, "2bar": 0.180, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 60; cherry 3; bar1/2 trimmed for bar_mixed cut
        {"blank": 0.600, "cherry": 0.030, "1bar": 0.115, "2bar": 0.095, "3bar": 0.045,
         "high7": 0.080, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 62; cherry 1.5
        {"blank": 0.620, "cherry": 0.015, "1bar": 0.090, "2bar": 0.080, "3bar": 0.060,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_D_focus_buckets():
    """D: focus on bucket math. ge5_lt10 needs +5pp from pay 7 (1bar 5x).
    P(pay 7) ~ p_1bar^3 (with no wild). To get 5pp RTP from 5x pay,
    need P(pay 7 base) = 1pp / 5x = 0.2% hit -> 1bar^3 ~ 0.002 ->
    1bar^3 ~ 2e-3 -> 1bar = 0.126. But also wild lifts contribute.
    Currently bar1 P 0.45% -> RTP 3.5pp. Need RTP ~8pp -> P ~1.0%.
    1bar^3 ~ 0.010 -> 1bar = 0.215. Aggressive.

    ge10_lt20 needs +5pp from pay 5 (2bar 10x). Currently bar2 P 0.43% -> 6.7pp.
    Need RTP ~9pp -> P ~0.6%. 2bar^3 ~ 0.006 -> 2bar = 0.18. Less aggressive.
    """
    return _balance_blank([
        # R1 — blank 35%; aggressively raise 1bar/2bar
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.220, "2bar": 0.200, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 55; 1bar/2bar similar
        {"blank": 0.550, "cherry": 0.030, "1bar": 0.150, "2bar": 0.135, "3bar": 0.055,
         "high7": 0.040, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 60
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.130, "2bar": 0.110, "3bar": 0.060,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_E_high7_keep():
    """E: D with high7 kept higher (preserve family share floor 2.5%)."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.210, "2bar": 0.195, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.555, "cherry": 0.030, "1bar": 0.145, "2bar": 0.135, "3bar": 0.055,
         "high7": 0.060, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.130, "2bar": 0.110, "3bar": 0.060,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_F_balance():
    """F: balanced. R1 blank 35, R2 56, R3 62. Bars escalated more."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.200, "2bar": 0.190, "3bar": 0.075,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.560, "cherry": 0.030, "1bar": 0.145, "2bar": 0.130, "3bar": 0.055,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.620, "cherry": 0.015, "1bar": 0.130, "2bar": 0.108, "3bar": 0.055,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_G_tune_bar2():
    """G: F with 2bar lift to push ge10_lt20."""
    m = candidate_F_balance()
    m[0]["2bar"] = 0.200
    m[1]["2bar"] = 0.140
    m[2]["2bar"] = 0.120
    return _balance_blank(m)


def candidate_H_tune_high7_low():
    """H: G with high7 trimmed to ~3% (lower family floor risk OK)."""
    m = candidate_G_tune_bar2()
    m[0]["high7"] = 0.030
    m[1]["high7"] = 0.040
    m[2]["high7"] = 0.025
    return _balance_blank(m)


def candidate_I_tune_bar3():
    """I: bar3 drop to compress ge20_lt50."""
    m = candidate_G_tune_bar2()
    m[0]["3bar"] = 0.065
    m[1]["3bar"] = 0.045
    m[2]["3bar"] = 0.045
    return _balance_blank(m)


def candidate_J_aggressive_bar2():
    """J: 2bar more aggressive. Test if bucket 10-20 hits +5pp target."""
    m = candidate_F_balance()
    m[0]["2bar"] = 0.220
    m[1]["2bar"] = 0.150
    m[2]["2bar"] = 0.130
    m[0]["1bar"] = 0.190
    m[1]["1bar"] = 0.135
    m[2]["1bar"] = 0.125
    return _balance_blank(m)


def candidate_K_combine_J():
    """K: J with cherry slightly dropped for bucket1to5 -10pp."""
    m = candidate_J_aggressive_bar2()
    m[0]["cherry"] = 0.025
    m[1]["cherry"] = 0.025
    m[2]["cherry"] = 0.012
    return _balance_blank(m)


def candidate_L_dial_bar3():
    """L: K with 3bar trim (bar3 cap risk)."""
    m = candidate_K_combine_J()
    m[0]["3bar"] = 0.060
    m[1]["3bar"] = 0.040
    m[2]["3bar"] = 0.045
    return _balance_blank(m)


def candidate_M_pure_strip():
    """M: tighter, more analytical.

    Goal RTP composition (target_v2 + user_brief):
      cherry1: 26-30% of base ~ 11-12pp -> match v9
      But user wants ge1_lt5 12.33pp total = cherry1 (~7) + bar_mixed (~5)
      So cherry1 ~ 7pp -> cherry hit ~ 7%
      cherry-anywhere: p_c ~ such that 1-(1-c1)(1-c2)(1-c3) ~ 7% -> c~0.025
      That's R1=R2=2.5%, R3=1.0%.

      bar_mixed: ~ 5pp -> bar_mixed hit ~ 2.5%.
        bar_mixed = (sum_p_bar)^3 - sum p^3 (combined sum)
        Need (Σ p_bar)^3 around 2.5% with high singles. Tight.

      bar1 (5x): RTP 8pp -> hit ~ 1.0% (with wild lift; pure 5x portion ~ 0.7%)
        1bar^3 cubed ~ 0.007 -> 1bar = 0.19. So 1bar marg ~ 19% each reel.

      bar2 (10x): RTP 9pp -> hit ~ 0.5% (pure 10x ~ 0.45%)
        2bar^3 ~ 0.0045 -> 2bar = 0.165.

      bar3 (20x): kept ~v9.
    """
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.220, "2bar": 0.180, "3bar": 0.080,
         "high7": 0.060, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.550, "cherry": 0.030, "1bar": 0.150, "2bar": 0.140, "3bar": 0.050,
         "high7": 0.040, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.130, "2bar": 0.115, "3bar": 0.060,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_N_tighten_M():
    """N: M but R2 1bar/2bar bumped slightly to fix bar1 < bar2 hierarchy."""
    m = candidate_M_pure_strip()
    # bar1 must remain > bar2 in hit. If 2bar marg > 1bar marg on a reel, fixing
    # by ensuring R1's 1bar >= 2bar
    m[0]["1bar"] = 0.230
    m[0]["2bar"] = 0.180
    m[1]["1bar"] = 0.155
    m[1]["2bar"] = 0.135
    m[2]["1bar"] = 0.135
    m[2]["2bar"] = 0.115
    return _balance_blank(m)


def candidate_O_3bar_compress():
    """O: 3bar slightly trimmed to free space for 1bar/2bar"""
    m = candidate_N_tighten_M()
    m[0]["3bar"] = 0.060
    m[1]["3bar"] = 0.040
    m[2]["3bar"] = 0.050
    return _balance_blank(m)


def candidate_P_high7_lift_compensation():
    """P: high7 R2 lifted to 7% to give some big-pay headroom (compensate
    feature RTP target). high7 30x with wild lift contributes to ge20_lt50 and
    larger buckets."""
    m = candidate_O_3bar_compress()
    m[0]["high7"] = 0.050
    m[1]["high7"] = 0.070
    m[2]["high7"] = 0.030
    return _balance_blank(m)


def candidate_Q_bar_more():
    """Q: bar1 and bar2 even more (since target is +5/+5 to those buckets)."""
    m = candidate_P_high7_lift_compensation()
    m[0]["1bar"] = 0.240
    m[0]["2bar"] = 0.190
    m[1]["1bar"] = 0.160
    m[1]["2bar"] = 0.140
    m[2]["1bar"] = 0.140
    m[2]["2bar"] = 0.120
    return _balance_blank(m)


def candidate_R_balance_RTP():
    """R: from Q, check RTP. If under 94%, lift 2bar more / high7."""
    m = candidate_Q_bar_more()
    return m


def candidate_S_drop_high7_to_3pct():
    """S: high7 cut to lower base RTP (compensate excess from bars)."""
    m = candidate_Q_bar_more()
    m[0]["high7"] = 0.035
    m[1]["high7"] = 0.050
    m[2]["high7"] = 0.025
    return _balance_blank(m)


def candidate_T_polish_S():
    """T: S with bar1 to 1bar slightly trim (RTP overshoot)."""
    m = candidate_S_drop_high7_to_3pct()
    m[0]["1bar"] = 0.230
    m[1]["1bar"] = 0.155
    m[2]["1bar"] = 0.135
    return _balance_blank(m)


def candidate_U_TT_polish():
    """U: T with cherry slightly back up — if cherry1 freq too low."""
    m = candidate_T_polish_S()
    m[0]["cherry"] = 0.030
    m[1]["cherry"] = 0.030
    m[2]["cherry"] = 0.015
    return _balance_blank(m)


def candidate_V_aggressive_1bar_only():
    """V: very heavy 1bar on R1 only; R2/R3 balanced bar1/2."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.290, "2bar": 0.180, "3bar": 0.060,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.560, "cherry": 0.030, "1bar": 0.150, "2bar": 0.140, "3bar": 0.045,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.135, "2bar": 0.115, "3bar": 0.050,
         "high7": 0.035, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_W_extreme_R1_winners():
    """W: R1 blank 32 (lower edge), max 1bar/2bar emphasis."""
    return _balance_blank([
        {"blank": 0.320, "cherry": 0.030, "1bar": 0.260, "2bar": 0.220, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.580, "cherry": 0.030, "1bar": 0.130, "2bar": 0.130, "3bar": 0.050,
         "high7": 0.040, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.620, "cherry": 0.012, "1bar": 0.130, "2bar": 0.115, "3bar": 0.055,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_X_R1_40_safer():
    """X: R1 blank 40 (upper edge), wider compensation room."""
    return _balance_blank([
        {"blank": 0.400, "cherry": 0.030, "1bar": 0.200, "2bar": 0.170, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.560, "cherry": 0.030, "1bar": 0.140, "2bar": 0.130, "3bar": 0.055,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.580, "cherry": 0.015, "1bar": 0.135, "2bar": 0.115, "3bar": 0.060,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_Y_R1_38():
    """Y: R1 blank 38 (slightly inside band)."""
    return _balance_blank([
        {"blank": 0.380, "cherry": 0.030, "1bar": 0.220, "2bar": 0.185, "3bar": 0.080,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.560, "cherry": 0.030, "1bar": 0.140, "2bar": 0.130, "3bar": 0.055,
         "high7": 0.050, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.130, "2bar": 0.115, "3bar": 0.055,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_Z_Y_lift_2bar():
    """Z: Y with R2/R3 2bar lifted more for ge10_lt20 +5pp target."""
    m = candidate_Y_R1_38()
    m[1]["2bar"] = 0.155
    m[2]["2bar"] = 0.135
    return _balance_blank(m)


def candidate_AA_Z_lift_1bar_R23():
    """AA: Z with R2/R3 1bar lifted for ge5_lt10 +5pp target."""
    m = candidate_Z_Y_lift_2bar()
    m[1]["1bar"] = 0.160
    m[2]["1bar"] = 0.150
    return _balance_blank(m)


def candidate_BB_AA_tune_R1_higher_1bar():
    """BB: AA with R1 1bar even higher."""
    m = candidate_AA_Z_lift_1bar_R23()
    m[0]["1bar"] = 0.250
    return _balance_blank(m)


def candidate_CC_R1_blank_35_balanced():
    """CC: balanced design around R1 blank 35.

    Math for bucket targets:
      ge1_lt5 RTP target 12.33pp:
        cherry1: ~7pp -> cherry-anywhere ~7%
          c1=c2=2.5%, c3=1.2% gives ~6.0% (close)
        bar_mixed: ~5pp -> hit 2.5% -> (Σ p_bar)^3 ~ 0.025 with subtract same_bar (small).
          On R1, R2, R3 if total bar = 40%, 30%, 30% -> 40*30*30 / 100^3 = 0.036 raw.
          With wild lift bar_mixed is hit when payline is 3 different bar types.
          P(line_3_group mixed bars) = product of bar marginals × C(bar_types: all-3-diff combos)
          ~ approx Σ_perm p_R1_b_i × p_R2_b_j × p_R3_b_k where i!=j!=k.
          Lower this by ensuring R2 has more 1bar (single dominant type).

      ge5_lt10 RTP target 8.72pp:
        bar1: ~6pp via pay 7 -> hit ~1.2%
          1bar^3 (across R1*R2*R3) ~ 0.012. With R1 1bar=0.24, R2=0.165, R3=0.135 ->
          product 0.24*0.165*0.135 = 0.00534. Cubed product gives ~0.5% pure.
          With wild lift (some wins shift to higher buckets but base pay rate ~1.0%).
        cherry2: ~2pp via pay 71 -> hit ~0.4%
          P(exactly 2 cherry on payline) = C(3,2) * c^2 * (1-c) sum, but cherry-count anywhere.
          ~ 3 * c1*c2*(1-c3) etc.

      ge10_lt20 RTP target 9.16pp:
        bar2 base 10x: ~7pp via pay 5 -> hit 0.7%
          2bar^3 ~ 0.007. R1*R2*R3 2bar = 0.18*0.135*0.115 = 0.0028. Too low.
          Need 2bar product ~0.007 -> R1=0.22 R2=0.20 R3=0.16. RTP cost moderate.
    """
    return _balance_blank([
        # R1 — blank 35, cherry 2.5, 1bar 24 (anchor 5x freq), 2bar 22 (anchor 10x), 3bar 7
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.240, "2bar": 0.220, "3bar": 0.060,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 53, cherry 2.5, 1bar 16, 2bar 19
        {"blank": 0.530, "cherry": 0.025, "1bar": 0.160, "2bar": 0.180, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 60, cherry 1.2, 1bar 14, 2bar 16
        {"blank": 0.600, "cherry": 0.012, "1bar": 0.140, "2bar": 0.160, "3bar": 0.045,
         "high7": 0.025, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_DD_CC_polish():
    """DD: CC with §1 hierarchy fix.

    Currently CC may have bar2 hit > bar1 hit since 2bar marg > 1bar marg.
    But §1 says bar1 (5x lowest) should have MORE hit.

    To fix: ensure 1bar marg > 2bar marg on each reel where possible. But
    we want pay 5 (10x bar2) RTP ~9pp -> 2bar product ~ 7e-3.
    And pay 7 (5x bar1) RTP ~6pp -> 1bar product ~ 12e-3.
    With wild lift these are within reach by 1bar > 2bar marginals.

    Test marginal product: 1bar^3 = 1.2e-2 -> 1bar avg = 0.228.
    2bar^3 = 7e-3 -> 2bar avg = 0.191.

    So 1bar > 2bar in marginal across reels. Hierarchy preserved.
    """
    return _balance_blank([
        # R1 — 1bar 24, 2bar 19, 3bar 6
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.240, "2bar": 0.200, "3bar": 0.065,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — 1bar 18, 2bar 16, 3bar 4
        {"blank": 0.540, "cherry": 0.025, "1bar": 0.180, "2bar": 0.165, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — 1bar 16, 2bar 14, 3bar 4
        {"blank": 0.610, "cherry": 0.012, "1bar": 0.150, "2bar": 0.145, "3bar": 0.045,
         "high7": 0.025, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_EE_DD_more_bars():
    """EE: DD with bar1/bar2 product larger to push buckets."""
    m = candidate_DD_CC_polish()
    m[1]["1bar"] = 0.190
    m[1]["2bar"] = 0.175
    m[2]["1bar"] = 0.160
    m[2]["2bar"] = 0.155
    return _balance_blank(m)


def candidate_FF_EE_more_3bar():
    """FF: EE with 3bar slight bump to keep bar3 family share above floor 5%."""
    m = candidate_EE_DD_more_bars()
    m[0]["3bar"] = 0.070
    m[1]["3bar"] = 0.045
    m[2]["3bar"] = 0.050
    return _balance_blank(m)


def candidate_GG_FF_drop_high7_more():
    """GG: FF with high7 lower (RTP overshoot likely)."""
    m = candidate_FF_EE_more_3bar()
    m[0]["high7"] = 0.030
    m[1]["high7"] = 0.025
    m[2]["high7"] = 0.020
    return _balance_blank(m)


def candidate_HH_GG_R1_36():
    """HH: GG with R1 blank 36% (slight inside)."""
    m = candidate_GG_FF_drop_high7_more()
    m[0]["blank"] = 0.360
    # Excess goes to 1bar / 2bar
    used = sum(v for k, v in m[0].items() if k != "blank")
    excess = 1 - used - 0.360
    m[0]["1bar"] += excess / 2
    m[0]["2bar"] += excess / 2
    return _balance_blank(m)


def candidate_II_simple_bar_focused():
    """II: simpler restart. Just heavy bars everywhere; cherry low; high7 low.

    Goal: hit ~17%, base RTP ~44pp. Buckets shift naturally.
    """
    return _balance_blank([
        # R1 — blank 35; bars heavy; cherry 2.5
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.265, "2bar": 0.225, "3bar": 0.060,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 55; bars moderate
        {"blank": 0.550, "cherry": 0.025, "1bar": 0.175, "2bar": 0.155, "3bar": 0.035,
         "high7": 0.025, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 60; bars trimmed for cap
        {"blank": 0.600, "cherry": 0.012, "1bar": 0.150, "2bar": 0.150, "3bar": 0.045,
         "high7": 0.020, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_JJ_II_polish():
    """JJ: II with high7 lifted to keep family share above floor 2.5%."""
    m = candidate_II_simple_bar_focused()
    m[0]["high7"] = 0.045
    m[1]["high7"] = 0.045
    m[2]["high7"] = 0.030
    return _balance_blank(m)


def candidate_KK_JJ_dd_lift():
    """KK: JJ with dd lift to ensure wild_pure floor 0.4%."""
    m = candidate_JJ_II_polish()
    m[0]["doublediamond"] = 0.035
    m[1]["doublediamond"] = 0.035
    m[2]["doublediamond"] = 0.014
    return _balance_blank(m)


def candidate_LL_KK_balance_RTP():
    """LL: KK adjusted for RTP 95% target."""
    m = candidate_KK_JJ_dd_lift()
    # If base RTP too high (likely with strong bars), trim 2bar slightly
    m[0]["2bar"] = 0.220
    m[1]["2bar"] = 0.150
    m[2]["2bar"] = 0.145
    return _balance_blank(m)


def candidate_MM_LL_more_bar3():
    """MM: LL with 3bar slightly back up (share-of-base floor 5%)."""
    m = candidate_LL_KK_balance_RTP()
    m[0]["3bar"] = 0.070
    m[1]["3bar"] = 0.045
    m[2]["3bar"] = 0.050
    return _balance_blank(m)


def candidate_NN_target_aligned():
    """NN: deliberate analytic target alignment.

    Targets:
      ge1_lt5 = cherry1 + bar_mixed = 12.33pp
        cherry1 ~7pp -> c_marg ~3.0/3.0/1.5%
        bar_mixed ~5pp -> bar_mixed hit ~2.5%
      ge5_lt10 = pay 7 base + pay 71 = 8.72pp
      ge10_lt20 = pay 5 base + pay 4 cherry3 (small) + pay 7 wild lifts = 9.16pp

    Per math: 1bar^3 ~ 1.2e-2 if 1bar avg = 0.228
    """
    return _balance_blank([
        # R1 — blank 36; cherry 3; 1bar 23, 2bar 19, 3bar 7
        {"blank": 0.360, "cherry": 0.030, "1bar": 0.230, "2bar": 0.190, "3bar": 0.065,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 55; cherry 3; 1bar 17, 2bar 15, 3bar 4
        {"blank": 0.550, "cherry": 0.030, "1bar": 0.170, "2bar": 0.150, "3bar": 0.040,
         "high7": 0.045, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 60; cherry 1.5; 1bar 15, 2bar 13, 3bar 5
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.150, "2bar": 0.130, "3bar": 0.050,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_OO_NN_balance():
    """OO: NN with slight 2bar lift on R2 for bucket 10-20 +5pp."""
    m = candidate_NN_target_aligned()
    m[1]["2bar"] = 0.165
    m[2]["2bar"] = 0.140
    return _balance_blank(m)


def candidate_PP_NN_lift_1bar_R1():
    """PP: OO with R1 1bar even higher."""
    m = candidate_OO_NN_balance()
    m[0]["1bar"] = 0.250
    m[0]["2bar"] = 0.180
    return _balance_blank(m)


def candidate_QQ_PP_high7_tune():
    """QQ: PP with high7 carefully tuned."""
    m = candidate_PP_NN_lift_1bar_R1()
    m[0]["high7"] = 0.040
    m[1]["high7"] = 0.055
    m[2]["high7"] = 0.030
    return _balance_blank(m)


def candidate_RR_QQ_clean():
    """RR: tighter than QQ."""
    m = candidate_QQ_PP_high7_tune()
    # Slight trim
    m[0]["1bar"] = 0.245
    m[0]["2bar"] = 0.175
    return _balance_blank(m)


def candidate_SS_heavy_1bar_per_reel():
    """SS: 1bar avg 26% across reels; 2bar 19%; 3bar 5%; cherry low.

    Math:
      ge5_lt10: 1bar^3 with no-wild ~ 0.247^3 = 0.015. Pure 5x ~ 1.4% hit ~ 7pp.
      ge10_lt20: 2bar^3 ~ 0.19^3 = 0.007. Pure 10x ~ 0.7% hit ~ 7pp + bar1 1-wild ~ 2pp = 9pp.
      ge1_lt5 cherry1: ~ 7pp -> cherry avg 2.5% (cherry-anywhere hit ~7%).
      bar_mixed: bar_total_per_reel = 26+19+5 = 50%. cubed ~ 0.125. all-same ~ 0.018+0.007+0.0001 = 0.025. mixed ~ 0.10. At 2x = 20pp.
      Too high! Need to suppress R2/R3 bar density.
    """
    return _balance_blank([
        # R1 — blank 35; 1bar 28, 2bar 19, 3bar 5
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.280, "2bar": 0.190, "3bar": 0.050,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 55; 1bar 17, 2bar 14, 3bar 4
        {"blank": 0.550, "cherry": 0.025, "1bar": 0.170, "2bar": 0.140, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 60; 1bar 15, 2bar 12, 3bar 4
        {"blank": 0.600, "cherry": 0.015, "1bar": 0.150, "2bar": 0.125, "3bar": 0.040,
         "high7": 0.025, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_TT_more_aggressive_bar_R1():
    """TT: R1 1bar 30%, 2bar 22%; lower R2/R3 to suppress bar_mixed."""
    return _balance_blank([
        {"blank": 0.330, "cherry": 0.025, "1bar": 0.300, "2bar": 0.220, "3bar": 0.045,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.580, "cherry": 0.025, "1bar": 0.165, "2bar": 0.130, "3bar": 0.030,
         "high7": 0.030, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.610, "cherry": 0.012, "1bar": 0.150, "2bar": 0.130, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_UU_R1_extra_1bar():
    """UU: R1 1bar 32%; R2/R3 moderate."""
    return _balance_blank([
        {"blank": 0.320, "cherry": 0.025, "1bar": 0.320, "2bar": 0.220, "3bar": 0.040,
         "high7": 0.040, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.570, "cherry": 0.025, "1bar": 0.170, "2bar": 0.130, "3bar": 0.030,
         "high7": 0.030, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.605, "cherry": 0.012, "1bar": 0.155, "2bar": 0.130, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_VV_balance_all_reels():
    """VV: all reels 1bar heavy to push bar1 hit. Compensate with low cherry."""
    return _balance_blank([
        {"blank": 0.320, "cherry": 0.020, "1bar": 0.290, "2bar": 0.230, "3bar": 0.045,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.560, "cherry": 0.020, "1bar": 0.180, "2bar": 0.145, "3bar": 0.030,
         "high7": 0.030, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.605, "cherry": 0.010, "1bar": 0.160, "2bar": 0.130, "3bar": 0.040,
         "high7": 0.025, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_WW_R1_blank_30():
    """WW: R1 blank 30 (edge), maximum 1bar/2bar boost."""
    return _balance_blank([
        {"blank": 0.300, "cherry": 0.020, "1bar": 0.320, "2bar": 0.240, "3bar": 0.040,
         "high7": 0.045, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.585, "cherry": 0.020, "1bar": 0.175, "2bar": 0.140, "3bar": 0.030,
         "high7": 0.025, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.620, "cherry": 0.010, "1bar": 0.155, "2bar": 0.130, "3bar": 0.040,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_XX_balanced_TT():
    """XX: TT polished."""
    m = candidate_TT_more_aggressive_bar_R1()
    # Bump R2 1bar to compensate weak bar1 hit
    m[1]["1bar"] = 0.180
    m[1]["2bar"] = 0.140
    m[2]["1bar"] = 0.160
    m[2]["2bar"] = 0.140
    return _balance_blank(m)


def candidate_YY_target_chase():
    """YY: explicit number-chase. R1 1bar 30%, 2bar 22%; R2 1bar 18%, 2bar 16%; R3 1bar 17%, 2bar 14%.

    Total bar per reel: 30+22+5=57; 18+16+4=38; 17+14+4=35.
    Sum of all non-blank: 57+~10 = 67 (R1); 38+~10 = 48; 35+~7 = 42.
    R1 blank = 100-67 = 33%. R2 blank = 52%. R3 blank = 58%.
    bar_mixed = 0.57 * 0.38 * 0.35 = 0.076 minus all_same.
    Higher than I want but let's see.
    """
    return _balance_blank([
        {"blank": 0.330, "cherry": 0.025, "1bar": 0.300, "2bar": 0.220, "3bar": 0.050,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.530, "cherry": 0.025, "1bar": 0.180, "2bar": 0.160, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.590, "cherry": 0.012, "1bar": 0.170, "2bar": 0.140, "3bar": 0.040,
         "high7": 0.025, "doublediamond": 0.012, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_ZZ_YY_more_2bar():
    """ZZ: YY with 2bar more aggressive on R1."""
    m = candidate_YY_target_chase()
    m[0]["2bar"] = 0.240
    return _balance_blank(m)


def candidate_AAA_target_hit_rate_recheck():
    """AAA: chase hit rate ~16-17% (within 15-18 band)."""
    return _balance_blank([
        # R1 — blank 35; 1bar 28, 2bar 20, 3bar 5; cherry 3
        {"blank": 0.350, "cherry": 0.030, "1bar": 0.280, "2bar": 0.200, "3bar": 0.050,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 53; 1bar 18, 2bar 16, 3bar 4; cherry 3
        {"blank": 0.530, "cherry": 0.030, "1bar": 0.180, "2bar": 0.160, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 59; 1bar 16, 2bar 14, 3bar 5; cherry 1.5
        {"blank": 0.590, "cherry": 0.015, "1bar": 0.165, "2bar": 0.150, "3bar": 0.050,
         "high7": 0.025, "doublediamond": 0.012, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_BBB_AAA_high7_lift():
    """BBB: AAA with high7 R2 ~5% to keep family share."""
    m = candidate_AAA_target_hit_rate_recheck()
    m[1]["high7"] = 0.050
    return _balance_blank(m)


def candidate_CCC_AAA_3bar_more():
    """CCC: AAA with 3bar slightly more (bar3 family share)."""
    m = candidate_AAA_target_hit_rate_recheck()
    m[0]["3bar"] = 0.060
    m[1]["3bar"] = 0.050
    m[2]["3bar"] = 0.055
    return _balance_blank(m)


def candidate_DDD_combined():
    """DDD: AAA + high7 lift + 3bar more."""
    m = candidate_AAA_target_hit_rate_recheck()
    m[1]["high7"] = 0.050
    m[0]["3bar"] = 0.060
    m[1]["3bar"] = 0.050
    m[2]["3bar"] = 0.055
    return _balance_blank(m)


def candidate_EEE_high7_low():
    """EEE: AAA with high7 trim (reduce RTP if overshoot)."""
    m = candidate_AAA_target_hit_rate_recheck()
    m[0]["high7"] = 0.035
    m[1]["high7"] = 0.025
    m[2]["high7"] = 0.020
    return _balance_blank(m)


def candidate_FFF_extreme_bars():
    """FFF: extreme bar density everywhere, low cherry."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.020, "1bar": 0.300, "2bar": 0.220, "3bar": 0.045,
         "high7": 0.040, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.540, "cherry": 0.020, "1bar": 0.195, "2bar": 0.165, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.585, "cherry": 0.010, "1bar": 0.180, "2bar": 0.150, "3bar": 0.055,
         "high7": 0.020, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_GGG_dial_in_R1blank_38():
    """GGG: R1 blank 38, with hit and bucket targets met."""
    return _balance_blank([
        {"blank": 0.380, "cherry": 0.030, "1bar": 0.265, "2bar": 0.200, "3bar": 0.050,
         "high7": 0.040, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.530, "cherry": 0.030, "1bar": 0.180, "2bar": 0.165, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.580, "cherry": 0.015, "1bar": 0.170, "2bar": 0.150, "3bar": 0.055,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_HHH_GGG_clean():
    """HHH: GGG with dd R3 trimmed (cadence ~ 1/80k)."""
    m = candidate_GGG_dial_in_R1blank_38()
    # bump dd back to v9-like for cadence
    m[0]["doublediamond"] = 0.032
    m[1]["doublediamond"] = 0.037
    m[2]["doublediamond"] = 0.014
    return _balance_blank(m)


def candidate_III_target_exact():
    """III: explicit target chase for bucket numbers.

    Goal:
      R1 blank ~ 35%, hit ~16%, RTP ~95%
      ge1_lt5 ~ 12.33 (cherry1+bar_mixed)
      ge5_lt10 ~ 8.72 (bar1+cherry2)
      ge10_lt20 ~ 9.16 (bar2+bar1-1wild lift)

    Working numbers (using analytic formulas):
      cherry: R1=2.5, R2=2.5, R3=1.2 -> cherry1 hit ~ 6.0%, RTP ~ 6.0pp
      1bar: R1=28, R2=18, R3=16 -> 1bar^3 = 0.28*0.18*0.16 = 8.06e-3 -> hit ~0.8%, RTP ~4pp at 5x base + wild lifts to ~7pp
      2bar: R1=20, R2=16, R3=14 -> 2bar^3 = 0.20*0.16*0.14 = 4.48e-3 -> hit ~0.45%, RTP ~4.5pp at 10x base + bar1 wild lift adds more
      3bar: R1=5, R2=4, R3=4.5 -> 3bar^3 = small
      bar_mixed: ~ (28+20+5)*(18+16+4)*(16+14+4.5) - all_same_bars ~ 53%*38%*34.5% = 6.95% raw, minus same-bar combos
    """
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.280, "2bar": 0.200, "3bar": 0.050,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.545, "cherry": 0.025, "1bar": 0.180, "2bar": 0.160, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.605, "cherry": 0.012, "1bar": 0.160, "2bar": 0.140, "3bar": 0.045,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_JJJ_III_R1_31():
    """JJJ: III with R1 blank 31, even more aggressive bars."""
    m = candidate_III_target_exact()
    m[0]["blank"] = 0.310
    used = sum(v for k, v in m[0].items() if k != "blank")
    excess = 1 - used - 0.310
    m[0]["1bar"] += excess * 0.6
    m[0]["2bar"] += excess * 0.4
    return _balance_blank(m)


def candidate_KKK_aggressive_winner():
    """KKK: aggressive bar push everywhere."""
    return _balance_blank([
        {"blank": 0.310, "cherry": 0.025, "1bar": 0.310, "2bar": 0.230, "3bar": 0.050,
         "high7": 0.045, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.520, "cherry": 0.025, "1bar": 0.195, "2bar": 0.170, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.012, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.590, "cherry": 0.012, "1bar": 0.175, "2bar": 0.150, "3bar": 0.050,
         "high7": 0.020, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_MMM_analytical_target():
    """MMM: deliberate analytic target.

    Based on per-bucket breakdown of v9:
      Target: pay 7 (5x base) hit ~1.0% -> 1bar^3 ~ 1.2% -> 1bar avg 22%
              pay 5 (10x base) hit ~0.55% -> 2bar^3 ~ 0.6% -> 2bar avg 18%
              cherry1 hit ~6% -> cherry-anywhere ~6% -> cherry avg ~2%
              bar_mixed hit ~2.5% -> sum_bar product ~ 2.5% + same_bar
                R1 sum_bar = 54, R2 = 42, R3 = 38 -> product 0.086 minus same_bar 0.014 -> 0.072. Too high.
                Need: 50 / 35 / 32 -> product 0.056 - 0.012 = 0.044. Still high.
                Maybe 40 / 28 / 25 -> 0.028 - 0.008 = 0.020. Better.

    Compromise: bar density per reel reduces from baseline to fit bar_mixed cap.
    """
    return _balance_blank([
        # R1 — blank 35; 1bar 22, 2bar 18, 3bar 5; cherry 2.5
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.270, "2bar": 0.220, "3bar": 0.050,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 50; 1bar 22, 2bar 18, 3bar 4
        {"blank": 0.500, "cherry": 0.025, "1bar": 0.220, "2bar": 0.180, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 55; 1bar 22, 2bar 18, 3bar 4
        {"blank": 0.550, "cherry": 0.010, "1bar": 0.180, "2bar": 0.180, "3bar": 0.045,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_NNN_MMM_higher_1bar_R1():
    """NNN: MMM with R1 1bar pushed higher (to push pay 7 hit)."""
    m = candidate_MMM_analytical_target()
    m[0]["1bar"] = 0.295
    m[0]["2bar"] = 0.205
    return _balance_blank(m)


def candidate_OOO_full_analytical():
    """OOO: full analytical target.

    Use per-bucket target math:
      pay 7 RTP target 6pp at 5x -> hit 1.2% -> 1bar^3 = 0.012 -> 1bar = 0.229
      pay 5 RTP target 5.5pp at 10x -> hit 0.55% -> 2bar^3 = 0.0055 -> 2bar = 0.177
      pay 7 1-wild RTP target 2.5pp at 10x -> 1bar^2 * dd*3 perm ~ 0.0025 -> ...
      cherry1 hit 6% -> cherry avg 2.0
      bar_mixed: must be lower. Total bar per reel: 1bar 23 + 2bar 18 + 3bar 4 = 45%.
        R1*R2*R3 sum_bar = 0.45 * 0.45 * 0.45 = 0.091. Minus same_bar (3 * 0.012 + 0.0005 + 0.0001) = 0.038. Still high.

      To suppress bar_mixed, vary bar mix per reel (concentrate 1bar on R1, 2bar on R2/R3).
        R1: 1bar 30, 2bar 10, 3bar 4 -> sum 44
        R2: 1bar 10, 2bar 25, 3bar 4 -> sum 39
        R3: 1bar 10, 2bar 25, 3bar 5 -> sum 40
        sum_bar product = 0.44 * 0.39 * 0.40 = 0.069. all-1bar = 0.30*0.10*0.10 = 0.003. all-2bar = 0.10*0.25*0.25 = 0.006. all-3bar = tiny. sum_same = 0.009. bar_mixed = 0.060. 12pp at 2x. Too high.

      Conclusion: bar_mixed structural minimum ~ 0.025-0.04 if bars dense.
      The bar_mixed RTP can include with-wild combos at 4x. Let's accept bar_mixed at 8-9pp and DEDUCT from total ge1_lt5 by cutting cherry1 down to ~3-4pp (cherry-anywhere hit ~3-4%).
    """
    return _balance_blank([
        # R1 — cherry 1.5, 1bar 23, 2bar 18, 3bar 5
        {"blank": 0.350, "cherry": 0.015, "1bar": 0.280, "2bar": 0.215, "3bar": 0.055,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — cherry 1.5
        {"blank": 0.500, "cherry": 0.015, "1bar": 0.230, "2bar": 0.180, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — cherry 0.5
        {"blank": 0.560, "cherry": 0.005, "1bar": 0.200, "2bar": 0.175, "3bar": 0.045,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_PPP_OOO_balanced():
    """PPP: OOO with high7 R2 lifted slightly (family floor 2.5%)."""
    m = candidate_OOO_full_analytical()
    m[1]["high7"] = 0.040
    return _balance_blank(m)


def candidate_QQQ_OOO_dd_more():
    """QQQ: OOO with dd back at v9 levels (cadence preserved)."""
    m = candidate_OOO_full_analytical()
    m[0]["doublediamond"] = 0.032
    m[1]["doublediamond"] = 0.037
    m[2]["doublediamond"] = 0.014
    return _balance_blank(m)


def candidate_RRR_OOO_combine():
    """RRR: OOO + high7 + dd."""
    m = candidate_OOO_full_analytical()
    m[1]["high7"] = 0.045
    m[0]["doublediamond"] = 0.032
    m[1]["doublediamond"] = 0.037
    m[2]["doublediamond"] = 0.014
    return _balance_blank(m)


def candidate_SSS_diff_bar_per_reel():
    """SSS: vary bar mix per reel — R1 1bar dominant, R2 2bar dominant, R3 1bar dominant.

    Goal: keep total bar product high (for bar1/bar2 hits) but lower
    bar_mixed (different bar types per reel rarer to match)."""
    return _balance_blank([
        # R1 — 1bar dominant
        {"blank": 0.350, "cherry": 0.020, "1bar": 0.330, "2bar": 0.175, "3bar": 0.040,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — 2bar dominant
        {"blank": 0.500, "cherry": 0.020, "1bar": 0.150, "2bar": 0.260, "3bar": 0.040,
         "high7": 0.030, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — 1bar dominant
        {"blank": 0.560, "cherry": 0.008, "1bar": 0.220, "2bar": 0.160, "3bar": 0.040,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_TTT_high_1bar_concentrate():
    """TTT: 1bar very concentrated per reel; 2bar moderate; 3bar low; high7 low; bar_mixed natural."""
    return _balance_blank([
        # R1
        {"blank": 0.350, "cherry": 0.020, "1bar": 0.350, "2bar": 0.180, "3bar": 0.040,
         "high7": 0.040, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        # R2
        {"blank": 0.490, "cherry": 0.020, "1bar": 0.270, "2bar": 0.150, "3bar": 0.035,
         "high7": 0.025, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        # R3
        {"blank": 0.580, "cherry": 0.008, "1bar": 0.220, "2bar": 0.140, "3bar": 0.040,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_UUU_balance_TTT():
    """UUU: TTT with cherry slightly higher (cherry1 hit not too tiny)."""
    m = candidate_TTT_high_1bar_concentrate()
    m[0]["cherry"] = 0.025
    m[1]["cherry"] = 0.025
    m[2]["cherry"] = 0.012
    return _balance_blank(m)


def candidate_VVV_TTT_more_2bar():
    """VVV: TTT with 2bar lifted for ge10_lt20 +5pp."""
    m = candidate_TTT_high_1bar_concentrate()
    m[0]["2bar"] = 0.210
    m[1]["2bar"] = 0.180
    m[2]["2bar"] = 0.155
    return _balance_blank(m)


def candidate_WWW_VVV_R1_38():
    """WWW: VVV with R1 blank 38."""
    m = candidate_VVV_TTT_more_2bar()
    m[0]["blank"] = 0.380
    used = sum(v for k, v in m[0].items() if k != "blank")
    excess = 1 - used - 0.380
    m[0]["1bar"] += excess
    return _balance_blank(m)


def candidate_XXX_VVV_R1_32():
    """XXX: VVV with R1 blank 32."""
    m = candidate_VVV_TTT_more_2bar()
    m[0]["blank"] = 0.320
    used = sum(v for k, v in m[0].items() if k != "blank")
    excess = 1 - used - 0.320
    m[0]["1bar"] += excess
    return _balance_blank(m)


def candidate_YYY_super_aggressive_1bar():
    """YYY: maximally push 1bar across reels."""
    return _balance_blank([
        # R1 — 1bar 38, 2bar 16, 3bar 4; cherry 2
        {"blank": 0.350, "cherry": 0.020, "1bar": 0.380, "2bar": 0.165, "3bar": 0.040,
         "high7": 0.040, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — 1bar 30, 2bar 14, 3bar 3
        {"blank": 0.490, "cherry": 0.020, "1bar": 0.300, "2bar": 0.140, "3bar": 0.035,
         "high7": 0.025, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — 1bar 24, 2bar 14, 3bar 4
        {"blank": 0.585, "cherry": 0.008, "1bar": 0.240, "2bar": 0.135, "3bar": 0.040,
         "high7": 0.020, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_ZZZ_balanced_winner():
    """ZZZ: balanced. R1 blank 35; cherry moderate; bars 1bar dominant per reel."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.310, "2bar": 0.200, "3bar": 0.045,
         "high7": 0.045, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.520, "cherry": 0.025, "1bar": 0.225, "2bar": 0.155, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.012, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.590, "cherry": 0.012, "1bar": 0.190, "2bar": 0.150, "3bar": 0.050,
         "high7": 0.022, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_AAAA_check_bucket_simulation():
    """AAAA: combo to check bucket distribution."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.020, "1bar": 0.330, "2bar": 0.190, "3bar": 0.045,
         "high7": 0.040, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.510, "cherry": 0.020, "1bar": 0.245, "2bar": 0.155, "3bar": 0.045,
         "high7": 0.025, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.580, "cherry": 0.010, "1bar": 0.210, "2bar": 0.145, "3bar": 0.050,
         "high7": 0.020, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_BBBB_AAAA_check_RTP():
    """BBBB: AAAA with high7 R2 5% (family share)."""
    m = candidate_AAAA_check_bucket_simulation()
    m[1]["high7"] = 0.050
    return _balance_blank(m)


def candidate_CCCC_AAAA_3bar_more():
    """CCCC: AAAA with 3bar slightly more (family share)."""
    m = candidate_AAAA_check_bucket_simulation()
    m[0]["3bar"] = 0.055
    m[1]["3bar"] = 0.050
    m[2]["3bar"] = 0.055
    return _balance_blank(m)


def candidate_DDDD_AAAA_lower_cherry():
    """DDDD: AAAA with cherry even lower."""
    m = candidate_AAAA_check_bucket_simulation()
    m[0]["cherry"] = 0.015
    m[1]["cherry"] = 0.015
    m[2]["cherry"] = 0.008
    return _balance_blank(m)


def candidate_EEEE_total_bar_balanced():
    """EEEE: deliberately push 1bar avg 26% across reels; 2bar avg 16%."""
    return _balance_blank([
        # R1 — 1bar 30, 2bar 18, 3bar 4
        {"blank": 0.350, "cherry": 0.025, "1bar": 0.300, "2bar": 0.190, "3bar": 0.045,
         "high7": 0.045, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — 1bar 24, 2bar 15, 3bar 4
        {"blank": 0.520, "cherry": 0.025, "1bar": 0.240, "2bar": 0.150, "3bar": 0.045,
         "high7": 0.040, "doublediamond": 0.027, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — 1bar 22, 2bar 14, 3bar 4
        {"blank": 0.595, "cherry": 0.010, "1bar": 0.215, "2bar": 0.140, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_LLL_test_low_cherry_extra():
    """LLL: cherry very low (1%) — push more RTP to bars."""
    return _balance_blank([
        {"blank": 0.350, "cherry": 0.010, "1bar": 0.290, "2bar": 0.230, "3bar": 0.050,
         "high7": 0.045, "doublediamond": 0.022, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.560, "cherry": 0.010, "1bar": 0.190, "2bar": 0.165, "3bar": 0.045,
         "high7": 0.030, "doublediamond": 0.012, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.610, "cherry": 0.005, "1bar": 0.170, "2bar": 0.150, "3bar": 0.055,
         "high7": 0.025, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


def candidate_FINAL_v10_winner():
    """FINAL v10 winner — best achievable subject to STRUCTURAL bar_mixed floor.

    Achievable:
      R1 blank ~ 35.3% (in [30, 40])  PASS
      hit ~ 16.8%        (in [15, 18])  PASS
      RTP ~ 95.8%        (in [94, 96])  PASS
      ge5_lt10 ~ 8.2pp   (in [8.0, 9.5])  PASS
      ge10_lt20 ~ 8.95pp (in [8.5, 10.0])  PASS
      ge1_lt5  ~ 24pp    STRUCTURAL FLOOR (target 12.33pp unreachable)

    Why structural: bar_mixed (pay 8, 2x) requires per-reel bar density of
    ~35-45% to push pay 7 (5x) and pay 5 (10x) base hits to fund ge5_lt10 +
    ge10_lt20 targets. sum_bar_product across 3 reels then forces bar_mixed
    hit ~ 9-10%, RTP ~ 19-20pp, all in ge1_lt5. Combined with cherry1 (~5pp
    minimum to keep cherry1 visible), ge1_lt5 cannot go below ~22pp.

    Mechanisms exhausted (per feedback_dont_lower_floor_when_blocked.md):
      A. Multiplicative boost: breaks RTP
      B. Mechanism-B blank redistribution: RTP-neutral, doesn't affect bucket
      C. Strip stop-count restructure: blocked by [STRIP-IMMUTABILITY]
      D. Paytable change: blocked by universal rule (proc_imp #36)
    """
    return _balance_blank([
        # R1 — blank 35; 1bar 31, 2bar 21.5, 3bar 4; cherry 2; high7 3.8; dd 2
        {"blank": 0.355, "cherry": 0.020, "1bar": 0.310, "2bar": 0.215, "3bar": 0.040,
         "high7": 0.038, "doublediamond": 0.020, "jackpot": 0.004, "topdollar": 0.0},
        # R2 — blank 47; 1bar 23.4, 2bar 19.3, 3bar 4; high7 2.8; dd 1.1
        {"blank": 0.478, "cherry": 0.020, "1bar": 0.234, "2bar": 0.193, "3bar": 0.040,
         "high7": 0.028, "doublediamond": 0.011, "jackpot": 0.004, "topdollar": 0.0},
        # R3 — blank 56.5; 1bar 21.5, 2bar 16.5, 3bar 4; high7 2; dd 0.5
        {"blank": 0.565, "cherry": 0.010, "1bar": 0.215, "2bar": 0.165, "3bar": 0.040,
         "high7": 0.020, "doublediamond": 0.005, "jackpot": 0.001, "topdollar": 0.011},
    ])


# -----------------------------------------------------------------------
# write final v10 weights
# -----------------------------------------------------------------------

def write_final_v10_mode1(target_marginals: list[dict[str, float]], feature_params: dict, out_path: Path, winner_name: str = "v10_winner"):
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
            "M15 v10 (2026-05-11 wave 5) — tighten 2 dimensions on top of v9.",
            "",
            "User pinned 2 hard targets (v9 acceptable; further tightening):",
            "  1. R1 blank marginal in [30, 40]% (v9 was 50.25%)",
            "  2. Bucket RTP shift:",
            "     ge1_lt5  RTP 22.33 -> 12.33pp  (cherry1 + bar_mixed trim)",
            "     ge5_lt10 RTP 3.72  -> 8.72pp   (bar1 5x boost)",
            "     ge10_lt20 RTP 4.16 -> 9.16pp   (bar2 10x boost)",
            "",
            f"Design narrative: session_artifacts/M15/design_v10.md",
            f"Feasibility audit: session_artifacts/M15/feasibility_v10.txt",
            f"Candidate: {winner_name}",
            "",
            "Live measured numbers via: python -m slot_designer.machines.M15.verify"
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": ["doublediamond", "high7", "topdollar"],
            "rationale": "Per philosophy §15.4 / §15.5: shift weight from non-top-adj Blanks to top-adj Blanks. Total Blank weight per reel preserved -> marginals unchanged -> RTP/hit/share invariant. v10 R1 blank now 30-40%, mechanism B still applied (RTP-neutral)."
        }
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def derive_mode7_weights(mode1_weights: list[list[int]], strips: list[list[str]], F: float = 1.30) -> list[list[int]]:
    """K-scaling derivation: blank weight * F; top weights * K such that
    top symbol marginals stay unchanged.

    K = (F * S_B + S_O) / (S_B + S_O) per reel.
    """
    out: list[list[int]] = []
    TOP_SYMS = {"doublediamond", "high7", "topdollar"}
    for r_idx, reel in enumerate(strips):
        old_weights = mode1_weights[r_idx]
        S_B = sum(old_weights[i] for i in range(len(reel)) if reel[i] == "blank")
        S_T = sum(old_weights[i] for i in range(len(reel)) if reel[i] in TOP_SYMS)
        S_O = sum(old_weights[i] for i in range(len(reel)) if reel[i] != "blank" and reel[i] not in TOP_SYMS)
        denom = S_B + S_O
        K = (F * S_B + S_O) / denom if denom > 0 else 1.0
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


def write_final_v10_mode7(mode1_weights_path: Path, feature_params: dict, out_path: Path, F: float = 1.30):
    m1 = json.loads(mode1_weights_path.read_text(encoding="utf-8"))
    strips = load_strips()
    mode7_weights = derive_mode7_weights(m1["weights"], strips, F=F)
    doc = {
        "machine": "M15",
        "mode": 7,
        "reel_set": "default",
        "weights": mode7_weights,
        "feature_params": feature_params,
        "_notes": [
            "M15 v10 mode 7 (2026-05-11 wave 5) — derived from mode 1 via K-scaling",
            "per user_brief v1.1 §e Option B:",
            "  - Top Dollar trigger rate = mode 1 (topdollar marg preserved)",
            "  - Big-pay frequencies (pay_id 1, 2, 21) = mode 1 (high7+dd preserved)",
            "  - Small-pay freqs cut: blank scaled by F=1.30; cherry/bars/jackpot",
            "    per-stop weights unchanged -> their marginals drop.",
            "  - Result: hit rate drops, RTP to ~85%.",
            "",
            "Live measured numbers via: python -m slot_designer.machines.M15.verify"
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": ["doublediamond", "high7", "topdollar"],
            "rationale": "Per philosophy §15.4 / §15.5: blank redistribution carries over from mode 1 base (K-scaling preserves top marginals)."
        }
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# -----------------------------------------------------------------------
# main
# -----------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys
    print("M15 v10 mode 1 candidate exploration")
    print("=" * 70)

    candidates = [
        ("A_v9_baseline", candidate_A_v9_baseline()),
        ("B_r1_blank_35_naive", candidate_B_r1_blank_35_naive()),
        ("C_cut_cherry_global", candidate_C_cut_cherry_global()),
        ("D_focus_buckets", candidate_D_focus_buckets()),
        ("E_high7_keep", candidate_E_high7_keep()),
        ("F_balance", candidate_F_balance()),
        ("G_tune_bar2", candidate_G_tune_bar2()),
        ("H_tune_high7_low", candidate_H_tune_high7_low()),
        ("I_tune_bar3", candidate_I_tune_bar3()),
        ("J_aggressive_bar2", candidate_J_aggressive_bar2()),
        ("K_combine_J", candidate_K_combine_J()),
        ("L_dial_bar3", candidate_L_dial_bar3()),
        ("M_pure_strip", candidate_M_pure_strip()),
        ("N_tighten_M", candidate_N_tighten_M()),
        ("O_3bar_compress", candidate_O_3bar_compress()),
        ("P_high7_lift", candidate_P_high7_lift_compensation()),
        ("Q_bar_more", candidate_Q_bar_more()),
        ("R_balance_RTP", candidate_R_balance_RTP()),
        ("S_drop_high7", candidate_S_drop_high7_to_3pct()),
        ("T_polish_S", candidate_T_polish_S()),
        ("U_TT_polish", candidate_U_TT_polish()),
        ("V_aggressive_1bar", candidate_V_aggressive_1bar_only()),
        ("W_extreme_R1_32", candidate_W_extreme_R1_winners()),
        ("X_R1_40_safer", candidate_X_R1_40_safer()),
        ("Y_R1_38", candidate_Y_R1_38()),
        ("Z_Y_lift_2bar", candidate_Z_Y_lift_2bar()),
        ("AA_Z_lift_1bar", candidate_AA_Z_lift_1bar_R23()),
        ("BB_AA_R1_more", candidate_BB_AA_tune_R1_higher_1bar()),
        ("CC_R1_blank_35", candidate_CC_R1_blank_35_balanced()),
        ("DD_CC_hierarchy", candidate_DD_CC_polish()),
        ("EE_DD_more_bars", candidate_EE_DD_more_bars()),
        ("FF_EE_more_3bar", candidate_FF_EE_more_3bar()),
        ("GG_FF_drop_high7", candidate_GG_FF_drop_high7_more()),
        ("HH_GG_R1_36", candidate_HH_GG_R1_36()),
        ("II_bar_focused", candidate_II_simple_bar_focused()),
        ("JJ_II_polish", candidate_JJ_II_polish()),
        ("KK_JJ_dd_lift", candidate_KK_JJ_dd_lift()),
        ("LL_KK_balance", candidate_LL_KK_balance_RTP()),
        ("MM_LL_more_bar3", candidate_MM_LL_more_bar3()),
        ("NN_target_aligned", candidate_NN_target_aligned()),
        ("OO_NN_balance", candidate_OO_NN_balance()),
        ("PP_NN_1bar_R1", candidate_PP_NN_lift_1bar_R1()),
        ("QQ_PP_high7", candidate_QQ_PP_high7_tune()),
        ("RR_QQ_clean", candidate_RR_QQ_clean()),
        ("SS_heavy_1bar", candidate_SS_heavy_1bar_per_reel()),
        ("TT_aggro_R1", candidate_TT_more_aggressive_bar_R1()),
        ("UU_R1_extra_1bar", candidate_UU_R1_extra_1bar()),
        ("VV_balance_all", candidate_VV_balance_all_reels()),
        ("WW_R1_blank_30", candidate_WW_R1_blank_30()),
        ("XX_balanced_TT", candidate_XX_balanced_TT()),
        ("YY_target_chase", candidate_YY_target_chase()),
        ("ZZ_more_2bar", candidate_ZZ_YY_more_2bar()),
        ("AAA_hit_recheck", candidate_AAA_target_hit_rate_recheck()),
        ("BBB_high7_lift", candidate_BBB_AAA_high7_lift()),
        ("CCC_3bar_more", candidate_CCC_AAA_3bar_more()),
        ("DDD_combined", candidate_DDD_combined()),
        ("EEE_high7_low", candidate_EEE_high7_low()),
        ("FFF_extreme_bars", candidate_FFF_extreme_bars()),
        ("GGG_R1blank_38", candidate_GGG_dial_in_R1blank_38()),
        ("HHH_GGG_clean", candidate_HHH_GGG_clean()),
        ("III_target_exact", candidate_III_target_exact()),
        ("JJJ_R1_31", candidate_JJJ_III_R1_31()),
        ("KKK_aggressive", candidate_KKK_aggressive_winner()),
        ("LLL_low_cherry", candidate_LLL_test_low_cherry_extra()),
        ("MMM_analytical", candidate_MMM_analytical_target()),
        ("NNN_R1_higher", candidate_NNN_MMM_higher_1bar_R1()),
        ("OOO_full_analytical", candidate_OOO_full_analytical()),
        ("PPP_OOO_high7", candidate_PPP_OOO_balanced()),
        ("QQQ_OOO_dd_more", candidate_QQQ_OOO_dd_more()),
        ("RRR_OOO_combine", candidate_RRR_OOO_combine()),
        ("SSS_diff_per_reel", candidate_SSS_diff_bar_per_reel()),
        ("TTT_high_1bar", candidate_TTT_high_1bar_concentrate()),
        ("UUU_TTT_cherry", candidate_UUU_balance_TTT()),
        ("VVV_TTT_more_2bar", candidate_VVV_TTT_more_2bar()),
        ("WWW_R1_38", candidate_WWW_VVV_R1_38()),
        ("XXX_R1_32", candidate_XXX_VVV_R1_32()),
        ("YYY_super_aggressive", candidate_YYY_super_aggressive_1bar()),
        ("ZZZ_balanced", candidate_ZZZ_balanced_winner()),
        ("AAAA_check_sim", candidate_AAAA_check_bucket_simulation()),
        ("BBBB_AAAA_high7", candidate_BBBB_AAAA_check_RTP()),
        ("CCCC_AAAA_3bar", candidate_CCCC_AAAA_3bar_more()),
        ("DDDD_AAAA_low_cherry", candidate_DDDD_AAAA_lower_cherry()),
        ("EEEE_total_bar_bal", candidate_EEEE_total_bar_balanced()),
        ("FINAL_v10_winner", candidate_FINAL_v10_winner()),
    ]

    results = []
    for name, m in candidates:
        try:
            res = evaluate_candidate(name, m, M1_FEATURE_PARAMS, apply_mech_b=True)
            results.append(res)
            print(print_candidate_report(res))
        except Exception as e:
            print(f"\n======== Candidate: {name} ERROR: {e}")
            import traceback; traceback.print_exc()

    print("\n\n" + "=" * 70)
    print("v10 Comparison summary (all hard targets)")
    print("=" * 70)
    headers = ["cand", "RTP%", "hit%", "R1blnk", "1to5pp", "5to10", "10to20", "ch1%h", "b1>b2", "RTPok", "HitOk", "R1ok", "BucksOk", "WINNER"]
    print(f"{'cand':<25s} {'RTP%':>7s} {'hit%':>7s} {'R1blnk':>8s} {'1to5':>7s} {'5to10':>7s} {'10to20':>7s} {'ch1%h':>7s} {'split':>10s}")
    for r in results:
        split_str = f"{r['base_share']:.1f}:{r['feat_share']:.1f}"
        r1b = r['reel_marginals'][0].get('blank', 0) * 100
        ok_rtp = 94.0 <= r['total_rtp_pct'] <= 96.0
        ok_hit = 15.0 <= r['profile']['hit_rate']*100 <= 18.0
        ok_r1 = 30.0 <= r1b <= 40.0
        ok_b1 = 11.5 <= r['bucket_1to5_rtp_pp'] <= 13.5
        ok_b2 = 8.0 <= r['bucket_5to10_rtp_pp'] <= 9.5
        ok_b3 = 8.5 <= r['bucket_10to20_rtp_pp'] <= 10.0
        all_pass = ok_rtp and ok_hit and ok_r1 and ok_b1 and ok_b2 and ok_b3
        print(f"{r['name']:<25s} {r['total_rtp_pct']:>7.2f} "
              f"{r['profile']['hit_rate']*100:>7.2f} {r1b:>8.2f} "
              f"{r['bucket_1to5_rtp_pp']:>7.2f} {r['bucket_5to10_rtp_pp']:>7.2f} "
              f"{r['bucket_10to20_rtp_pp']:>7.2f} {r['cherry1_share_of_hit']*100:>7.2f} "
              f"{split_str:>10s} {'***WINNER***' if all_pass else ''}")

    # If requested, write the final weights for the chosen winner
    if "--write" in _sys.argv:
        # Find the first all-pass candidate by name we want
        winner_idx = None
        winner_arg = None
        for i, a in enumerate(_sys.argv):
            if a == "--winner":
                winner_arg = _sys.argv[i+1]
        if winner_arg:
            for r in results:
                if r["name"] == winner_arg:
                    winner_marginals = r["target_marginals"]
                    out_m1 = WEIGHTS_DIR / "mode_1" / "weights.json"
                    write_final_v10_mode1(winner_marginals, M1_FEATURE_PARAMS, out_m1, winner_name=winner_arg)
                    print(f"\n[WROTE] {out_m1}")
                    out_m7 = WEIGHTS_DIR / "mode_7" / "weights.json"
                    write_final_v10_mode7(out_m1, M1_FEATURE_PARAMS, out_m7)
                    print(f"[WROTE] {out_m7}")
                    break
