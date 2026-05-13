"""M15 v10c mode 1 redesign — v10b retry with user-authorized §2 cherry relaxation.

Stage 4 retry (2026-05-11 wave 6) after v10b structural escalation. User
adjudicated with explicit §2 cherry visibility relaxation:

    Cherry per-reel marginal CAN drop to ~2-3.5% (was 3-6% archetype floor).
    M15 cherry becomes deliberately rarer than IGT classic archetype.
    This is an *owned §2 deviation* specific to M15 v10c.

USER PINNED (v10c, must ALL pass):
  - R1 blank marginal in [30%, 40%]
  - ge1_lt5 RTP in [11.0pp, 14.0pp]
  - ge5_lt10 RTP in [8.0pp, 9.5pp]
  - ge10_lt20 RTP in [8.5pp, 10.0pp]
  - hit in [15%, 18%]
  - total RTP in [94%, 96%]
  - P(R>=1000)/spin <= 1e-5
  - jackpot any-reel <= 0.6%

PHILOSOPHY-DERIVED (still HARD):
  - wild_pure cadence in [1/50k, 1/120k]
  - R1 max single non-blank marginal <= 22%
  - §1 hierarchy: bar_mixed > bar1 > bar2 > bar3 in hit; cherry1 > cherry2 > cherry3
  - doublediamond per-reel >= 1.5%, high7 >= 2.5%, topdollar on R3 ~= 1.1%

§2 RELAXED (per user authorization):
  - Cherry marginal floor lowered to 2.0% per reel
  - Cherry-1 dominance: any value (no §8 cap — cherry-1 will be less dominant naturally)

KEY INSIGHT from v10b:
  v9 cherry ~5% / 5% / 2.5% → cherry-1 P=11.53%, RTP=11.53pp (sole ge1_lt5
  bloater). Drop cherry to ~2-3% per reel:
    P(cherry-1) ≈ 3 * c * (1-c)^2 ≈ 3 * 0.03 * 0.94 ≈ 8.46%  → 8.46pp
  ge1_lt5 budget freed: ~3pp. Combined with bar_mixed cut (Lever A), ge1_lt5
  reaches [11, 14] band.

  Bar lifts to fill ge5_lt10 and ge10_lt20:
    bar1 marginal ~20%/reel → bar1 pure P ≈ 0.20^3 = 0.8%  → 4pp RTP (5×)
                          + bar1+wild combos ~0.7%  → 7pp (5×2=10×, ge10_lt20)
    bar2 marginal ~17%/reel → bar2 pure P ≈ 0.17^3 = 0.5%  → 5pp (10×)
                          + bar2+wild combos lift ge20_lt50
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
    _round_payout_distribution,
    analyze_feature,
)

_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
SPEC_PATH = _M15_DIR / "spec.json"
STRIPS_PATH = _M15_DIR / "reel_strips.json"
WEIGHTS_DIR = _M15_DIR / "weights"


# Feature params — keep v9 byte-identical (preserves feature RTP/EV/CV)
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


# ----------------------------------------------------------------------
# strip helpers (reused from v10b)
# ----------------------------------------------------------------------

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
    """Convert per-reel target marginals to integer per-stop weights.

    Auto-normalizes each reel's target marginals to sum to 1.0 (so authors
    can write rough numbers and they re-normalize cleanly).
    """
    weights: list[list[int]] = []
    counts_per_reel = stop_counts_per_reel(strips)
    for r_idx, reel in enumerate(strips):
        target = target_marginals[r_idx]
        s = sum(target.values())
        target_norm = {k: v / s for k, v in target.items()} if s > 0 else target
        counts = counts_per_reel[r_idx]
        wps: dict[str, int] = {}
        for sym, frac in target_norm.items():
            if sym not in counts:
                continue
            cnt = counts[sym]
            w_float = scale * frac / cnt
            wps[sym] = max(1, int(round(w_float)))
        reel_weights = []
        for s_sym in reel:
            reel_weights.append(int(wps.get(s_sym, 1)))
        weights.append(reel_weights)
    return weights


def apply_mechanism_b_blanks(
    strips: list[list[str]],
    weights: list[list[int]],
    top_symbols: set[str] = frozenset(("doublediamond", "high7", "topdollar")),
    non_top_adj_floor: int = 1,
) -> list[list[int]]:
    """Per philosophy §15.4 / §15.5: redistribute blank weight per reel."""
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


# ----------------------------------------------------------------------
# evaluate candidate
# ----------------------------------------------------------------------

def evaluate_candidate(
    name: str,
    target_marginals: list[dict[str, float]],
    feature_params: dict = M1_FEATURE_PARAMS,
    *,
    apply_mech_b: bool = True,
    scale: int = 10000,
) -> dict:
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
    import os
    tmp_path = _ROOT / "session_artifacts" / "M15" / f"_tmp_v10c_candidate_{os.getpid()}.json"
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

    # buckets (pp = percentage points)
    bucket_rtp = profile["bucket_rtp"]
    bucket_ge1_lt5_pp = bucket_rtp.get("ge1_lt5", 0.0) * 100.0
    bucket_ge5_lt10_pp = bucket_rtp.get("ge5_lt10", 0.0) * 100.0
    bucket_ge10_lt20_pp = bucket_rtp.get("ge10_lt20", 0.0) * 100.0

    # PWDF top symbols any-reel max
    top_window = {}
    for sym in ("doublediamond", "high7", "topdollar"):
        max_pw = 0.0
        for strip in reel_strips_dict:
            pw = symbol_window_probability(strip, sym)
            if pw > max_pw:
                max_pw = pw
        top_window[sym] = max_pw

    # pay_id hits
    pay_hits = profile["pay_hits"]
    pay_rtp = profile["pay_rtp"]
    bar_mixed_p = pay_hits.get("8", 0.0)
    bar1_p = pay_hits.get("7", 0.0)
    bar2_p = pay_hits.get("5", 0.0)
    bar3_p = pay_hits.get("3", 0.0)
    cherry1_p = pay_hits.get("9", 0.0)
    cherry2_p = pay_hits.get("71", 0.0)
    cherry3_p = pay_hits.get("4", 0.0)
    wild_p = pay_hits.get("1", 0.0)
    high7_wild_p = pay_hits.get("2", 0.0)
    high7_pure_p = pay_hits.get("21", 0.0)
    wild_cadence = (1.0 / wild_p) if wild_p > 0 else float("inf")

    # R1 max non-blank marginal
    r1_max_non_blank = max(
        ((s, v) for s, v in margs[0].items() if s != "blank"),
        key=lambda x: x[1],
        default=("", 0.0),
    )

    # PWDF mid-pay floor check (cherry remains visible)
    cherry_window = {}
    for r_idx, strip in enumerate(reel_strips_dict):
        cherry_window[f"R{r_idx+1}"] = symbol_window_probability(strip, "cherry")

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
        "base_pp": profile["rtp_pct"],
        "feat_pp": feature_rtp_pp,
        "p_r_ge_1000_per_spin": p_r_ge_1000_per_spin,
        "bucket_ge1_lt5_pp": bucket_ge1_lt5_pp,
        "bucket_ge5_lt10_pp": bucket_ge5_lt10_pp,
        "bucket_ge10_lt20_pp": bucket_ge10_lt20_pp,
        "top_window": top_window,
        "cherry_window": cherry_window,
        "bar_mixed_p": bar_mixed_p,
        "bar1_p": bar1_p,
        "bar2_p": bar2_p,
        "bar3_p": bar3_p,
        "cherry1_p": cherry1_p,
        "cherry2_p": cherry2_p,
        "cherry3_p": cherry3_p,
        "wild_p": wild_p,
        "high7_wild_p": high7_wild_p,
        "high7_pure_p": high7_pure_p,
        "wild_cadence": wild_cadence,
        "r1_max_non_blank": r1_max_non_blank,
        "pay_rtp": pay_rtp,
        "pay_hits": pay_hits,
    }


HARD_CONSTRAINTS = {
    "hit": (lambda r: r["profile"]["hit_rate"] * 100, 15.0, 18.0, "{:.3f}%"),
    "total_rtp": (lambda r: r["total_rtp_pct"], 94.0, 96.0, "{:.3f}%"),
    "R1_blank": (lambda r: r["reel_marginals"][0].get("blank", 0) * 100, 30.0, 40.0, "{:.2f}%"),
    "bucket_ge1_lt5_RTP": (lambda r: r["bucket_ge1_lt5_pp"], 11.0, 14.0, "{:.3f}pp"),
    "bucket_ge5_lt10_RTP": (lambda r: r["bucket_ge5_lt10_pp"], 8.0, 9.5, "{:.3f}pp"),
    "bucket_ge10_lt20_RTP": (lambda r: r["bucket_ge10_lt20_pp"], 8.5, 10.0, "{:.3f}pp"),
    "P(R>=1000)/spin": (lambda r: r["p_r_ge_1000_per_spin"], 0, 1e-5, "{:.2e}"),
    "wild_cadence_1_in": (lambda r: r["wild_cadence"], 50000, 120000, "{:.0f}"),
    "R1_max_single_non_blank": (
        lambda r: r["r1_max_non_blank"][1] * 100, 0, 22.0, "{:.2f}%",
    ),
    "jackpot_R1_marg": (lambda r: r["reel_marginals"][0].get("jackpot", 0) * 100, 0, 0.6, "{:.3f}%"),
    "jackpot_R2_marg": (lambda r: r["reel_marginals"][1].get("jackpot", 0) * 100, 0, 0.6, "{:.3f}%"),
    "jackpot_R3_marg": (lambda r: r["reel_marginals"][2].get("jackpot", 0) * 100, 0, 0.6, "{:.3f}%"),
}


def check_hard_constraints(res: dict) -> list[tuple[str, str, str, str]]:
    out = []
    for name, (getter, lo, hi, fmt) in HARD_CONSTRAINTS.items():
        v = getter(res)
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        status = "PASS" if ok else "FAIL"
        out.append((
            name, fmt.format(v),
            f"[{fmt.format(lo) if lo is not None else '-inf'}, {fmt.format(hi) if hi is not None else '+inf'}]",
            status,
        ))
    return out


def check_archetype_bands(res: dict) -> list[tuple[str, str, str, str]]:
    """Philosophy §2 archetype-visibility, with v10c cherry relaxation:
    cherry: 2-6% (relaxed floor from 3 to 2 per user authorization)
    doublediamond: 1.0-5% (kept; user_brief: >= 1.5%)
    high7: 2.5-8.5% (kept; user_brief: >= 2.5%)
    """
    out = []
    margs = res["reel_marginals"]
    for r_idx in range(3):
        for sym, lo, hi in [
            ("cherry", 2.0, 6.0),
            ("doublediamond", 1.0, 5.0),
            ("high7", 2.5, 8.5),
        ]:
            v = margs[r_idx].get(sym, 0) * 100
            ok = lo <= v <= hi
            out.append((
                f"R{r_idx+1}_{sym}_marg", f"{v:.2f}%",
                f"[{lo}, {hi}]", "PASS" if ok else "FAIL",
            ))
    return out


def check_hierarchy(res: dict) -> list[tuple[str, str]]:
    """§1 bar inverse pyramid: bar1 >= bar2 >= bar3 (HIT freq).
    Also report bar_mixed > bar1 expectation."""
    out = []
    bm = res["bar_mixed_p"]
    b1 = res["bar1_p"]
    b2 = res["bar2_p"]
    b3 = res["bar3_p"]
    out.append(("bar1>=bar2", "PASS" if b1 >= b2 - 1e-5 else "FAIL"))
    out.append(("bar2>=bar3", "PASS" if b2 >= b3 - 1e-5 else "FAIL"))
    out.append(("bar_mixed>bar1", "PASS" if bm >= b1 else "FAIL"))
    c1 = res["cherry1_p"]
    c2 = res["cherry2_p"]
    c3 = res["cherry3_p"]
    out.append(("cherry1>=cherry2", "PASS" if c1 >= c2 - 1e-5 else "FAIL"))
    out.append(("cherry2>=cherry3", "PASS" if c2 >= c3 - 1e-5 else "FAIL"))
    return out


def print_candidate_report(res: dict) -> str:
    lines = [f"\n======== Candidate: {res['name']} ========"]
    p = res["profile"]
    margs = res["reel_marginals"]
    lines.append(f"Total RTP:   {res['total_rtp_pct']:.3f}%  (base {res['base_pp']:.2f} / feat {res['feat_pp']:.2f})")
    lines.append(f"Hit rate:    {p['hit_rate']*100:.3f}%")
    lines.append(f"Trigger:     {res['trigger_rate']*100:.3f}%  (1 in {1/res['trigger_rate']:.0f})" if res['trigger_rate'] > 0 else "Trigger:     n/a")
    lines.append(f"Wild cadence: 1 in {res['wild_cadence']:.0f}")
    lines.append("Per-reel marginals:")
    for r_idx in range(3):
        m = margs[r_idx]
        lines.append(
            f"  R{r_idx+1}: blank={m.get('blank',0)*100:5.2f}%  cherry={m.get('cherry',0)*100:5.2f}%  "
            f"1bar={m.get('1bar',0)*100:5.2f}%  2bar={m.get('2bar',0)*100:5.2f}%  "
            f"3bar={m.get('3bar',0)*100:5.2f}%  high7={m.get('high7',0)*100:5.2f}%  "
            f"dd={m.get('doublediamond',0)*100:5.2f}%  jp={m.get('jackpot',0)*100:4.2f}%  td={m.get('topdollar',0)*100:4.2f}%"
        )

    lines.append("")
    lines.append("Buckets (RTP-pp):")
    lines.append(f"  ge1_lt5   = {res['bucket_ge1_lt5_pp']:.3f}pp   (target [11, 14])")
    lines.append(f"  ge5_lt10  = {res['bucket_ge5_lt10_pp']:.3f}pp  (target [8, 9.5])")
    lines.append(f"  ge10_lt20 = {res['bucket_ge10_lt20_pp']:.3f}pp (target [8.5, 10])")

    lines.append("")
    lines.append("Hierarchy:")
    lines.append(
        f"  bar_mixed P={res['bar_mixed_p']*100:.4f}%  bar1 P={res['bar1_p']*100:.4f}%  "
        f"bar2 P={res['bar2_p']*100:.4f}%  bar3 P={res['bar3_p']*100:.4f}%"
    )
    lines.append(
        f"  cherry1 P={res['cherry1_p']*100:.4f}%  cherry2 P={res['cherry2_p']*100:.4f}%  "
        f"cherry3 P={res['cherry3_p']*100:.4f}%"
    )
    for name, status in check_hierarchy(res):
        lines.append(f"    {name}: {status}")

    lines.append("")
    lines.append("Pay RTP contributions (pp):")
    for pid in ["9", "8", "71", "7", "5", "3", "4", "21", "2", "1"]:
        if pid in res["pay_rtp"]:
            lines.append(
                f"  pay_id {pid:3s} P={res['pay_hits'].get(pid, 0)*100:7.4f}%  "
                f"RTP={res['pay_rtp'].get(pid, 0)*100:7.4f}pp"
            )

    lines.append("")
    lines.append("PWDF top-symbol any-reel max:")
    for sym in ("doublediamond", "high7", "topdollar"):
        pw = res["top_window"].get(sym, 0)
        lines.append(f"  {sym}: {pw*100:.2f}%")
    lines.append("Cherry mid-pay window visibility per reel:")
    for k, v in res["cherry_window"].items():
        lines.append(f"  {k}: {v*100:.2f}%")

    lines.append("")
    lines.append("Hard constraint table:")
    rows = check_hard_constraints(res)
    n_pass = sum(1 for r in rows if r[3] == "PASS")
    for name, val, band, stat in rows:
        lines.append(f"  {name:32s} {val:>12s}  band={band:30s}  {stat}")
    lines.append(f"  -- {n_pass}/{len(rows)} PASS --")

    lines.append("")
    lines.append("Archetype-band table (philosophy §2, v10c cherry relaxed to 2%):")
    arows = check_archetype_bands(res)
    n_apass = sum(1 for r in arows if r[3] == "PASS")
    for name, val, band, stat in arows:
        lines.append(f"  {name:32s} {val:>10s}  band={band:18s}  {stat}")
    lines.append(f"  -- {n_apass}/{len(arows)} PASS --")
    return "\n".join(lines)


# ======================================================================
# Candidate marginal designs — v10c with cherry relaxed
# ======================================================================
#
# Math intuition for cherry-1 RTP at low marginal:
#   c_r = cherry marginal per reel r
#   P(cherry-1) = 3 * mean(c_r) * (1 - mean(c_r))^2  approximately
#   (exact = sum over single-cherry placements with the other two reels
#    being non-cherry/non-wild substituted differently per cherry_count rule)
#
# v9 baseline:
#   cherry marginals (5/5/2.5) → cherry-1 P 11.53%, RTP 11.53pp
#
# v10c target:
#   cherry marginals (2.5/2.5/2.5) → cherry-1 P ~7.1%, RTP ~7.1pp
#   plus bar_mixed cut: 3bar marginal ~2-3% per reel → bar_mixed P drops ~50%
#   → bar_mixed RTP from 10.80pp → ~5pp
#   ge1_lt5 = cherry-1 + bar_mixed ≈ 7 + 5 = ~12pp  → in [11, 14] band

def candidate_A_cherry_25_bars_lift():
    """A: cherry uniform 2.5% per reel; bars lifted; 3bar trimmed."""
    return [
        # R1: cherry 2.5%, 1bar 21%, 2bar 19%, 3bar 3%, high7 5%, dd 3.2%
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.210, "2bar": 0.190, "3bar": 0.030,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        # R2: cherry 2.5%, 1bar 19.5%, 2bar 18%, 3bar 3%, high7 8.2%, dd 3.7%
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.195, "2bar": 0.180, "3bar": 0.030,
         "high7": 0.082, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        # R3: cherry 2.5%, 1bar 21%, 2bar 19%, 3bar 3.5%, high7 4%, dd 1.4%, td 1.1%
        {"blank": 0.43, "cherry": 0.025, "1bar": 0.205, "2bar": 0.180, "3bar": 0.035,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_B_cherry_30():
    """B: cherry 3.0% per reel (slightly higher); bars slightly lower."""
    return [
        {"blank": 0.39, "cherry": 0.030, "1bar": 0.205, "2bar": 0.185, "3bar": 0.030,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.39, "cherry": 0.030, "1bar": 0.190, "2bar": 0.175, "3bar": 0.030,
         "high7": 0.082, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.43, "cherry": 0.030, "1bar": 0.200, "2bar": 0.180, "3bar": 0.035,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.010},
    ]


def candidate_C_cherry_20_bars_max():
    """C: cherry 2.0% (floor); bars near R1 max cap to push buckets."""
    return [
        {"blank": 0.37, "cherry": 0.020, "1bar": 0.220, "2bar": 0.200, "3bar": 0.025,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.38, "cherry": 0.020, "1bar": 0.205, "2bar": 0.190, "3bar": 0.025,
         "high7": 0.082, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.42, "cherry": 0.020, "1bar": 0.215, "2bar": 0.190, "3bar": 0.030,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.010},
    ]


def candidate_D_cherry_30_R1_38():
    """D: cherry 3.0%, R1 blank 38% (high end of band)."""
    return [
        {"blank": 0.38, "cherry": 0.030, "1bar": 0.205, "2bar": 0.190, "3bar": 0.035,
         "high7": 0.052, "doublediamond": 0.033, "jackpot": 0.005, "topdollar": 0.0},
        {"blank": 0.38, "cherry": 0.030, "1bar": 0.195, "2bar": 0.180, "3bar": 0.035,
         "high7": 0.083, "doublediamond": 0.038, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.42, "cherry": 0.030, "1bar": 0.200, "2bar": 0.180, "3bar": 0.040,
         "high7": 0.040, "doublediamond": 0.015, "jackpot": 0.001, "topdollar": 0.010},
    ]


def candidate_E_cherry_25_tighter():
    """E: cherry 2.5%, bars precisely tuned for ge5/ge10 to hit mid-band."""
    return [
        # 1bar/2bar slightly higher to push bar1 and bar2 hit
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.215, "2bar": 0.190, "3bar": 0.025,
         "high7": 0.053, "doublediamond": 0.030, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.200, "2bar": 0.180, "3bar": 0.025,
         "high7": 0.085, "doublediamond": 0.038, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.43, "cherry": 0.025, "1bar": 0.205, "2bar": 0.180, "3bar": 0.030,
         "high7": 0.042, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_F_asymmetric_R3_cherry():
    """F: cherry R1=2.5, R2=2.5, R3=3.5 — push cherry-pair/triple higher.
    Goal: more cherry2/3 into ge5/10 buckets without inflating cherry-1.
    """
    return [
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.210, "2bar": 0.190, "3bar": 0.030,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.195, "2bar": 0.180, "3bar": 0.030,
         "high7": 0.083, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.43, "cherry": 0.035, "1bar": 0.198, "2bar": 0.180, "3bar": 0.030,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_G_cherry_28_bars_balanced():
    """G: cherry 2.8%, RTP-balanced bars."""
    return [
        {"blank": 0.39, "cherry": 0.028, "1bar": 0.208, "2bar": 0.188, "3bar": 0.030,
         "high7": 0.052, "doublediamond": 0.031, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.39, "cherry": 0.028, "1bar": 0.193, "2bar": 0.178, "3bar": 0.030,
         "high7": 0.083, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.43, "cherry": 0.028, "1bar": 0.200, "2bar": 0.182, "3bar": 0.035,
         "high7": 0.041, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


def candidate_H_cherry_25_more_2bar():
    """H: cherry 2.5%, more 2bar (lift ge10_lt20 via bar2 pure 10×)."""
    return [
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.200, "2bar": 0.205, "3bar": 0.030,
         "high7": 0.050, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.39, "cherry": 0.025, "1bar": 0.185, "2bar": 0.195, "3bar": 0.030,
         "high7": 0.082, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
        {"blank": 0.43, "cherry": 0.025, "1bar": 0.195, "2bar": 0.195, "3bar": 0.035,
         "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
    ]


# Note: §1 hierarchy requires bar1 >= bar2 in HIT frequency. P(bar_n) for pure
# bar_n is approximately marginal_bar_n^3. So if marginal(1bar) >= marginal(2bar),
# the cubic relationship preserves bar1 hit >= bar2 hit (P~marg^3). For mixed
# bar_mixed we need 3*p1*p2*p3*6 etc., and bar_mixed.P >> bar1.P naturally.


# Mode 7 derivation: same K-scaling as v9
def derive_mode7_weights(
    mode1_weights: list[list[int]], strips: list[list[str]], F: float = 1.30
) -> list[list[int]]:
    """K-scale derivation: scale blank by F; scale top symbols by K so that
    top marginals stay UNCHANGED. cherry/bars/jackpot drop proportionally.

    K per reel = (F * S_B + S_O) / (S_B + S_O)
    """
    out: list[list[int]] = []
    TOP_SYMS = {"doublediamond", "high7", "topdollar"}
    for r_idx, reel in enumerate(strips):
        old_weights = mode1_weights[r_idx]
        S_B = sum(old_weights[i] for i in range(len(reel)) if reel[i] == "blank")
        S_T = sum(old_weights[i] for i in range(len(reel)) if reel[i] in TOP_SYMS)
        S_O = sum(
            old_weights[i]
            for i in range(len(reel))
            if reel[i] != "blank" and reel[i] not in TOP_SYMS
        )
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


# ----------------------------------------------------------------------
# Write final
# ----------------------------------------------------------------------

def write_final_v10c_mode1(
    target_marginals: list[dict[str, float]],
    feature_params: dict,
    out_path: Path,
    candidate_name: str,
):
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
            "M15 v10c (2026-05-11 wave 6) — v10b retry with §2 cherry relaxation.",
            "User adjudicated v10b structural escalation by authorizing cherry",
            "marginal floor reduction from 3.5% to 2.0% per reel (owned §2",
            "deviation, M15-specific).",
            "",
            "v10c targets ALL hit:",
            "  - R1 blank in [30%, 40%]",
            "  - ge1_lt5 RTP in [11.0pp, 14.0pp]",
            "  - ge5_lt10 RTP in [8.0pp, 9.5pp]",
            "  - ge10_lt20 RTP in [8.5pp, 10.0pp]",
            "  - hit in [15%, 18%]",
            "  - total RTP in [94%, 96%]",
            "  - P(R>=1000)/spin <= 1e-5",
            "  - jackpot <= 0.6%/reel",
            "",
            "Levers applied:",
            "  - Cherry relaxed: 5/5/2.5 → 2.5/2.5/2.5 per user §2 relaxation",
            "    → cherry-1 RTP drops ~11.5pp → ~7pp (frees ge1_lt5 budget)",
            "  - 3bar trimmed: 8/7/9 → ~3/3/3.5 (cuts bar_mixed cubic)",
            "  - 1bar/2bar lifted to ~20% per reel (push bar1/bar2 pure pays)",
            "  - R1 blank dropped 50% → ~38-39% (mass to bars)",
            "  - Mechanism B retained for PWDF visibility",
            "  - Feature params byte-identical to v9 (preserves feature RTP/EV/CV)",
            "",
            f"Final candidate: {candidate_name}",
            "Feasibility audit: session_artifacts/M15/feasibility_v10c.txt",
            "Live measured numbers via: python -m slot_designer.machines.M15.verify",
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": ["doublediamond", "high7", "topdollar"],
            "rationale": "Per philosophy §15.4 / §15.5 — preserved (RTP-neutral).",
        },
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def write_final_v10c_mode7(
    mode1_weights_path: Path, feature_params: dict, out_path: Path, F: float = 1.30
):
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
            "M15 v10c mode 7 (2026-05-11 wave 6) — derived from mode 1 via",
            f"K-scaling (F={F}), same mechanism as v9.",
            "",
            "Per user_brief v1.1 §e Option B (精神等价):",
            "  - Top Dollar trigger rate = mode 1 (topdollar marg preserved)",
            "  - Big-pay frequencies (pay_id 1, 2, 21) = mode 1 (high7+dd preserved)",
            "  - Small-pay freqs cut: blank scaled by F; cherry/bars/jackpot",
            "    per-stop weights unchanged → marginals drop.",
            "  - Result: hit rate drops to ~14-15%, RTP to ~83-85%.",
            "",
            "Live measured numbers via: python -m slot_designer.machines.M15.verify",
        ],
        "_v81_mechanism_b": {
            "method": "mechanism_b_rtp_neutral_blank_redistribute",
            "non_top_adj_floor": 1,
            "top_symbols": ["doublediamond", "high7", "topdollar"],
            "rationale": "Per philosophy §15.4 / §15.5: blank redistribution carries over.",
        },
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# Main exploration
# ----------------------------------------------------------------------

CANDIDATES = [
    ("A_cherry_25_bars_lift", candidate_A_cherry_25_bars_lift),
    ("B_cherry_30", candidate_B_cherry_30),
    ("C_cherry_20_bars_max", candidate_C_cherry_20_bars_max),
    ("D_cherry_30_R1_38", candidate_D_cherry_30_R1_38),
    ("E_cherry_25_tighter", candidate_E_cherry_25_tighter),
    ("F_asymmetric_R3_cherry", candidate_F_asymmetric_R3_cherry),
    ("G_cherry_28_bars_balanced", candidate_G_cherry_28_bars_balanced),
    ("H_cherry_25_more_2bar", candidate_H_cherry_25_more_2bar),
]


if __name__ == "__main__":
    print("M15 v10c mode 1 candidate exploration (cherry relaxed to 2-3.5%)")
    print("=" * 80)
    results = []
    for name, builder in CANDIDATES:
        m = builder()
        for i, r in enumerate(m):
            s = sum(r.values())
            if abs(s - 1.0) > 0.01:
                print(f"  WARN: {name} R{i+1} sums to {s:.4f}")
        res = evaluate_candidate(name, m)
        results.append(res)
        print(print_candidate_report(res))

    # summary
    print("\n\n" + "=" * 80)
    print("All-hard-constraints summary")
    print("=" * 80)
    print(f"{'cand':<26s} {'RTP%':>7s} {'hit%':>7s} {'R1blnk':>7s} "
          f"{'g1l5':>6s} {'g5l10':>6s} {'g10l20':>7s} "
          f"{'wildC':>8s} {'R1max':>6s} {'PASS/N':>6s}")
    for r in results:
        rows = check_hard_constraints(r)
        n_pass = sum(1 for x in rows if x[3] == "PASS")
        n_tot = len(rows)
        wc = r["wild_cadence"]
        wc_str = f"{wc/1000:.0f}k" if wc < 1e6 else "inf"
        print(
            f"{r['name']:<26s} {r['total_rtp_pct']:>7.2f} "
            f"{r['profile']['hit_rate']*100:>7.2f} "
            f"{r['reel_marginals'][0].get('blank',0)*100:>7.2f} "
            f"{r['bucket_ge1_lt5_pp']:>6.2f} {r['bucket_ge5_lt10_pp']:>6.2f} "
            f"{r['bucket_ge10_lt20_pp']:>7.2f} "
            f"{wc_str:>8s} "
            f"{r['r1_max_non_blank'][1]*100:>5.1f} "
            f"{n_pass}/{n_tot}"
        )
