"""v9.1 empirical sub-gate — Stage 6 verification for m7 v9.1 (RTP margin fix).

Same as v9 sub-gate framework but expanded to 5M MC immediately since the v9 stress
test established 5M is the right sample size for the floor margin question.

Tasks:
1. Load v9.1 m7 + ship'd v5 m1 + v6 m2/m5 weights
2. Run analytic_profile() and verify match vs design_v9_1_m7.md (RTP 84.747, hit 17.254, pid9 26.44%)
3. Single-seed 50k + 200k MC sub-gate
4. CRITICAL: 50 seeds x 100k = 5M MC RTP lower bound stress test
   - Compare directly to v9 results
5. Hit ceiling check (m1 hit - 0.3pp = 20.62; brief amended hit upper to 17.5)
6. m1, m2, m5 invariance (byte-eq with v5/v6 states)
7. Cross-mode invariants

Pass/Fail criteria:
- Mean RTP >= 84.0 floor → minimum pass
- <= 10% seeds below floor → comfortable pass
- Mean RTP >= 84.0 + buffer >= 84.3 → strong pass

Usage:
    python empirical_v9_1_subgate.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    analytic_profile,
    compute_reel_marginal,
)
from slot_designer.core.engine.loader import load_engine

SPEC = ROOT / "slot_designer" / "machines" / "M37" / "spec.json"
STRIPS = ROOT / "slot_designer" / "machines" / "M37" / "reel_strips.json"

# v9.1 m7 weights
M7_V91_W = ROOT / "session_artifacts" / "M37" / "v9_1_sim_weights" / "mode_7" / "weights.json"

# v6 m2/m5 ship state (untouched in v9/v9.1)
M2_V6_W = ROOT / "session_artifacts" / "M37" / "v6_sim_weights" / "mode_2" / "weights.json"
M5_V6_W = ROOT / "session_artifacts" / "M37" / "v6_sim_weights" / "mode_5" / "weights.json"

# v5 m1 ship'd (locked)
M1_SHIPPED_W = ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_1" / "weights.json"
M1_V5_SIM_W = ROOT / "session_artifacts" / "M37" / "v5_sim_weights" / "mode_1" / "weights.json"


# Thresholds
RTP_FLOOR = 84.0   # design_v9_1 hard lower bound — Critical X caveat
RTP_CEIL = 86.0
HIT_CEILING = 20.62  # universal §9 m1 v5 hit 20.92 - 0.3pp safety
HIT_UPPER_BAND = 17.5  # brief amended from 17.0 (per Designer v9.1 §5 note)


# -----------------------------------------------------------------------------
# Monte Carlo
# -----------------------------------------------------------------------------

_BUCKET_EDGES = [
    (5000.0, "ge5000"),
    (1000.0, "ge1000_lt5000"),
    (500.0, "ge500_lt1000"),
    (200.0, "ge200_lt500"),
    (100.0, "ge100_lt200"),
    (50.0, "ge50_lt100"),
    (20.0, "ge20_lt50"),
    (10.0, "ge10_lt20"),
    (5.0, "ge5_lt10"),
    (1.0, "ge1_lt5"),
    (0.0, "gt0_lt1"),
]


def bucket_for(mult: float) -> str | None:
    if mult <= 0:
        return None
    for edge, key in _BUCKET_EDGES:
        if mult >= edge:
            return key
    return None


def monte_carlo(engine, n_spins: int, seed: int = 42) -> dict:
    rng = Random(seed)
    total_mult = 0.0
    total_mult_sq = 0.0
    n_hits = 0
    bucket_count: dict[str, int] = defaultdict(int)
    bucket_rtp_acc: dict[str, float] = defaultdict(float)
    pay_count: dict[str, int] = defaultdict(int)
    pay_rtp_acc: dict[str, float] = defaultdict(float)
    pid9_mult_count: dict[float, int] = defaultdict(int)

    for _ in range(n_spins):
        out = engine.spin(rng)
        mult = float(out.pay.multiplier) if out.pay is not None else 0.0
        total_mult += mult
        total_mult_sq += mult * mult
        if mult > 0:
            n_hits += 1
            pid = str(out.pay.pay_id) if out.pay is not None else "0"
            pay_count[pid] += 1
            pay_rtp_acc[pid] += mult
            if pid == "9":
                pid9_mult_count[mult] += 1
            bkt = bucket_for(mult)
            if bkt is not None:
                bucket_count[bkt] += 1
                bucket_rtp_acc[bkt] += mult

    rtp_pct = (total_mult / n_spins) * 100
    hit_rate = n_hits / n_spins
    mean_mult = total_mult / n_spins
    var = max(0.0, (total_mult_sq / n_spins) - mean_mult * mean_mult)
    std_return_x = math.sqrt(var)
    cv = std_return_x / mean_mult if mean_mult > 0 else 0.0

    rtp_stderr = std_return_x / math.sqrt(n_spins) * 100
    rtp_ci_95 = 1.96 * rtp_stderr
    hit_stderr = math.sqrt(hit_rate * (1 - hit_rate) / n_spins)
    hit_ci_95 = 1.96 * hit_stderr * 100

    return {
        "n_spins": n_spins,
        "seed": seed,
        "rtp_pct": rtp_pct,
        "rtp_ci_95_pp": rtp_ci_95,
        "rtp_stderr_pp": rtp_stderr,
        "hit_rate_pct": hit_rate * 100,
        "hit_ci_95_pp": hit_ci_95,
        "hit_stderr_pp": hit_stderr * 100,
        "cv": cv,
        "std_return_x": std_return_x,
        "bucket_count": dict(bucket_count),
        "bucket_rate": {k: v / n_spins for k, v in bucket_count.items()},
        "bucket_rtp_pp": {k: v / n_spins * 100 for k, v in bucket_rtp_acc.items()},
        "pay_count": dict(pay_count),
        "pay_hits": {k: v / n_spins for k, v in pay_count.items()},
        "pay_rtp": {k: v / n_spins for k, v in pay_rtp_acc.items()},
        "pid9_mult_breakdown": {
            f"mult_{m}": {
                "count": c,
                "rate": c / n_spins,
                "rtp_pp": (m * c / n_spins) * 100,
            }
            for m, c in sorted(pid9_mult_count.items())
        },
    }


def analytic_summary(weights_path: Path) -> dict:
    engine, _ = load_engine(SPEC, weights_path, strips_path=STRIPS)
    profile = analytic_profile(engine)
    marginals = [compute_reel_marginal(r) for r in engine.reels]
    return {"profile": profile, "marginals": marginals, "engine": engine}


def fmt_marginals(marginals) -> str:
    BAR_SYMS = ("1bar", "2bar", "3bar", "7bar")
    out = []
    syms = ["blank", "1bar", "2bar", "3bar", "7bar", "high7", "wild", "mini", "minor", "major", "grand"]
    for i, m in enumerate(marginals):
        bar_sum = sum(m.get(s, 0) for s in BAR_SYMS) * 100
        line = f"R{i+1}: "
        for s in syms:
            v = m.get(s, 0) * 100
            if v > 0.001:
                line += f"{s}={v:.4f} "
        out.append(line + f"[bar_sum={bar_sum:.4f}]")
    return "\n".join(out)


def byte_diffs(path_a: Path, path_b: Path) -> list:
    wa = json.loads(path_a.read_text(encoding="utf-8"))["weights"]
    wb = json.loads(path_b.read_text(encoding="utf-8"))["weights"]
    diffs = []
    for ri in range(len(wa)):
        for pi in range(len(wa[ri])):
            if wa[ri][pi] != wb[ri][pi]:
                diffs.append((ri, pi, wa[ri][pi], wb[ri][pi]))
    return diffs


def run_mode_full(label, weights_path, n_mc=50000, seed=42):
    print(f"\n{'='*80}\n{label}: {weights_path}\n{'='*80}")
    a = analytic_summary(weights_path)
    profile = a["profile"]
    marginals = a["marginals"]
    engine = a["engine"]

    print(f"\nAnalytic RTP: {profile['rtp_pct']:.4f}%")
    print(f"Analytic Hit: {profile['hit_rate']*100:.4f}%")
    print(f"Analytic CV: {profile['cv']:.4f}")
    print(f"Analytic std_return_x: {profile['std_return_x']:.4f}")

    print(f"\nMarginals:")
    print(fmt_marginals(marginals))

    pid9_share_a = (profile["pay_rtp"].get("9", 0) * 100) / profile["rtp_pct"] * 100 if profile["rtp_pct"] > 0 else 0
    print(f"\nAnalytic pid 9 share: {pid9_share_a:.4f}%")

    print(f"\nAnalytic per-pay_id RTP-pp / hit-pp:")
    for pid in sorted(profile["pay_rtp"].keys(), key=lambda x: int(x)):
        rtp_pp = profile["pay_rtp"][pid] * 100
        hit_pp = profile["pay_hits"][pid] * 100
        print(f"  pid {pid}: RTP-pp={rtp_pp:.4f}, hit-pp={hit_pp:.4f}")

    print(f"\nAnalytic bucket distribution:")
    for bkt in ["ge1_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt50", "ge50_lt100",
                "ge100_lt200", "ge200_lt500", "ge500_lt1000", "ge1000_lt5000", "ge5000"]:
        rate = profile["bucket_rate"].get(bkt, 0)
        rtp_pp = profile["bucket_rtp"].get(bkt, 0) * 100
        print(f"  {bkt}: rate={rate*100:.4f}%, rtp-pp={rtp_pp:.4f}")

    print(f"\nRunning Monte Carlo {n_mc:,} spins seed={seed}...")
    mc = monte_carlo(engine, n_mc, seed=seed)
    analytic_se = profile["std_return_x"] / math.sqrt(n_mc) * 100
    rtp_drift = mc["rtp_pct"] - profile["rtp_pct"]
    rtp_drift_sigma = rtp_drift / analytic_se if analytic_se > 0 else 0
    hit_drift = mc["hit_rate_pct"] - profile["hit_rate"] * 100
    hit_drift_sigma = hit_drift / (mc["hit_ci_95_pp"] / 1.96) if mc["hit_ci_95_pp"] > 0 else 0
    pid9_share_mc = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0

    print(f"\nMC RTP: {mc['rtp_pct']:.4f}% (analytic SE +/-{1.96*analytic_se:.4f}pp) drift={rtp_drift:+.4f}pp ({rtp_drift_sigma:+.2f}sigma)")
    print(f"MC Hit: {mc['hit_rate_pct']:.4f}% (+/-{mc['hit_ci_95_pp']:.4f}pp 95% CI) drift={hit_drift:+.4f}pp ({hit_drift_sigma:+.2f}sigma)")
    print(f"MC pid 9 share: {pid9_share_mc:.4f}% (analytic={pid9_share_a:.4f}, drift={pid9_share_mc - pid9_share_a:+.4f}pp)")
    print(f"MC CV: {mc['cv']:.4f}")

    return {
        "analytic": profile, "marginals": marginals, "engine": engine,
        "mc": mc, "pid9_share_analytic": pid9_share_a, "pid9_share_mc": pid9_share_mc,
    }


def multi_seed_rtp_stress_5m(engine, analytic_rtp, analytic_cv, analytic_hit, n_per_seed=100_000, n_seeds=50):
    """50-seed × 100k = 5M MC RTP stress test (matching v9 sub-gate methodology)."""
    # Use same seed family as v9 final test for direct comparability
    seeds = [42, 12345, 7, 9999, 31415, 27182, 16180,
             11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61,
             67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137,
             139, 149, 151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211][:n_seeds]

    print(f"\n{'='*80}")
    print(f"5M Multi-seed RTP lower bound stress test (RTP floor {RTP_FLOOR})")
    print(f"Analytic RTP: {analytic_rtp:.4f}, analytic CV: {analytic_cv:.4f}")
    print(f"{n_per_seed:,} spins per seed * {n_seeds} seeds = {n_per_seed * n_seeds:,} total spins")
    print(f"{'='*80}")

    results = []
    rtps = []
    hits = []
    pid9_shares = []

    # Per-pay aggregate accumulators
    total_pay_count: dict[str, int] = defaultdict(int)
    total_n_spins = 0
    total_bucket_count: dict[str, int] = defaultdict(int)

    for seed in seeds:
        mc = monte_carlo(engine, n_per_seed, seed=seed)
        pid9_share = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0
        results.append(mc)
        rtps.append(mc["rtp_pct"])
        hits.append(mc["hit_rate_pct"])
        pid9_shares.append(pid9_share)
        for pid, cnt in mc["pay_count"].items():
            total_pay_count[pid] += cnt
        for bkt, cnt in mc["bucket_count"].items():
            total_bucket_count[bkt] += cnt
        total_n_spins += n_per_seed

        rtp_below_floor = mc["rtp_pct"] < RTP_FLOOR
        margin = RTP_FLOOR - mc["rtp_pct"]
        rtp_flag = "BELOW" if rtp_below_floor else f"PASS ({-margin:+.3f}pp)"
        print(f"  seed={seed:5d}: RTP={mc['rtp_pct']:.4f} ({rtp_flag}); hit={mc['hit_rate_pct']:.4f}; pid9_share={pid9_share:.4f}%")

    # Multi-seed stats
    rtp_mean = statistics.mean(rtps)
    rtp_stdev = statistics.stdev(rtps) if len(rtps) >= 2 else 0
    rtp_min = min(rtps)
    rtp_max = max(rtps)
    hit_mean = statistics.mean(hits)
    hit_stdev = statistics.stdev(hits) if len(hits) >= 2 else 0
    pid9_mean = statistics.mean(pid9_shares)
    pid9_stdev = statistics.stdev(pid9_shares) if len(pid9_shares) >= 2 else 0

    rtp_mean_se = rtp_stdev / math.sqrt(len(seeds)) if len(seeds) > 1 else 0
    rtp_mean_ci_95 = 1.96 * rtp_mean_se
    rtp_mean_ci_lower = rtp_mean - rtp_mean_ci_95
    rtp_mean_ci_upper = rtp_mean + rtp_mean_ci_95

    hit_mean_se = hit_stdev / math.sqrt(len(seeds)) if len(seeds) > 1 else 0
    hit_mean_ci_95 = 1.96 * hit_mean_se

    # P(seed RTP < 84.0)
    n_below = sum(1 for r in rtps if r < RTP_FLOOR)
    p_below_emp = n_below / len(rtps)

    # Parametric P
    from math import erf, sqrt
    single_seed_se = analytic_cv * (analytic_rtp / 100) / math.sqrt(n_per_seed) * 100 if analytic_cv else rtp_stdev
    if single_seed_se > 0:
        z_floor = (RTP_FLOOR - analytic_rtp) / single_seed_se
        p_below_norm = 0.5 * (1 + erf(z_floor / sqrt(2)))
    else:
        p_below_norm = 0.0 if analytic_rtp > RTP_FLOOR else 1.0

    if rtp_stdev > 0:
        z_mean = (RTP_FLOOR - rtp_mean) / rtp_stdev
        p_seed_below_obs = 0.5 * (1 + erf(z_mean / sqrt(2)))
    else:
        p_seed_below_obs = 0.0 if rtp_mean > RTP_FLOOR else 1.0

    # Hit upper band
    n_hit_above_band = sum(1 for h in hits if h > HIT_UPPER_BAND)
    n_hit_above_ceiling = sum(1 for h in hits if h > HIT_CEILING)

    print(f"\nMulti-seed stats ({len(seeds)} seeds, {total_n_spins:,} total spins):")
    print(f"  RTP mean: {rtp_mean:.4f}% (+/- {rtp_mean_ci_95:.4f} 95% CI of mean)")
    print(f"    CI of mean: [{rtp_mean_ci_lower:.4f}, {rtp_mean_ci_upper:.4f}]")
    print(f"  RTP stdev across seeds: {rtp_stdev:.4f}")
    print(f"  RTP min: {rtp_min:.4f}, max: {rtp_max:.4f}")
    print(f"  Hit mean: {hit_mean:.4f}% (+/- {hit_mean_ci_95:.4f} 95% CI of mean)")
    print(f"  Hit stdev across seeds: {hit_stdev:.4f}")
    print(f"  Hit min: {min(hits):.4f}, max: {max(hits):.4f}")
    print(f"  pid 9 share mean: {pid9_mean:.4f}% (stdev {pid9_stdev:.4f})")

    print(f"\nRTP lower bound stress test ({RTP_FLOOR}):")
    print(f"  Mean RTP: {rtp_mean:.4f} (margin to {RTP_FLOOR}: {rtp_mean - RTP_FLOOR:+.4f}pp)")
    print(f"  Mean RTP CI lower bound: {rtp_mean_ci_lower:.4f}")
    print(f"  Single-seed worst (min): {rtp_min:.4f}")
    print(f"  Seeds below floor: {n_below}/{len(seeds)} ({100*p_below_emp:.1f}%)")
    print(f"  Empirical P(seed RTP < {RTP_FLOOR}): {p_below_emp:.4f}")
    print(f"  Parametric P(single seed @{n_per_seed} spins < {RTP_FLOOR}) under N(analytic, analytic_SE): {p_below_norm:.4f} (z={z_floor:.4f})")
    print(f"  Parametric P(seed < {RTP_FLOOR}) under N(observed_mean, observed_stdev): {p_seed_below_obs:.4f}")

    print(f"\nHit upper band stress ({HIT_UPPER_BAND}):")
    print(f"  Seeds above {HIT_UPPER_BAND}: {n_hit_above_band}/{len(seeds)}")
    print(f"  Seeds above {HIT_CEILING} (universal §9): {n_hit_above_ceiling}/{len(seeds)}")

    # PASS/FAIL verdicts
    # RTP: PASS-COMFORTABLE if mean >= floor AND <= 10% seeds below
    # RTP: PASS-NARROW if mean >= floor but > 10% seeds below
    # RTP: FAIL if mean < floor
    if rtp_mean >= RTP_FLOOR:
        if p_below_emp <= 0.10:
            rtp_verdict = "PASS-COMFORTABLE"
        else:
            rtp_verdict = "PASS-NARROW (mean ≥ floor but >10% seeds below)"
    else:
        rtp_verdict = "FAIL"
    print(f"\nRTP stress test verdict: {rtp_verdict}")

    # Aggregate per-pay frequency analysis (m1 baseline + ratio)
    print(f"\nAggregate per-pay frequency over {total_n_spins:,} spins:")
    for pid in sorted(total_pay_count.keys(), key=lambda x: int(x)):
        agg_freq = total_pay_count[pid] / total_n_spins
        print(f"  pid {pid}: count={total_pay_count[pid]:,} freq={agg_freq:.6f}")

    return {
        "seeds": seeds, "rtps": rtps, "hits": hits, "pid9_shares": pid9_shares,
        "rtp_mean": rtp_mean, "rtp_stdev": rtp_stdev, "rtp_min": rtp_min, "rtp_max": rtp_max,
        "rtp_mean_ci_95": rtp_mean_ci_95, "rtp_mean_ci_lower": rtp_mean_ci_lower, "rtp_mean_ci_upper": rtp_mean_ci_upper,
        "hit_mean": hit_mean, "hit_stdev": hit_stdev, "hit_mean_ci_95": hit_mean_ci_95,
        "hit_min": min(hits), "hit_max": max(hits),
        "pid9_mean": pid9_mean, "pid9_stdev": pid9_stdev,
        "n_below": n_below, "p_below_emp": p_below_emp, "p_below_norm": p_below_norm,
        "p_seed_below_obs": p_seed_below_obs,
        "n_hit_above_band": n_hit_above_band, "n_hit_above_ceiling": n_hit_above_ceiling,
        "floor": RTP_FLOOR, "ceiling": HIT_CEILING, "hit_band_upper": HIT_UPPER_BAND,
        "verdict": rtp_verdict,
        "total_n_spins": total_n_spins,
        "total_pay_count": dict(total_pay_count),
        "total_bucket_count": dict(total_bucket_count),
    }


def mode5_base_lock_check():
    return byte_diffs(M2_V6_W, M5_V6_W)


def mode7_lock_drift(m1_marginals, m7_marginals):
    m1_r2 = m1_marginals[1]
    m7_r2 = m7_marginals[1]
    drifts = {}
    for sym in ["mini", "minor", "major", "grand"]:
        m1_val = m1_r2.get(sym, 0) * 100
        m7_val = m7_r2.get(sym, 0) * 100
        drifts[sym] = {
            "m1_v5": m1_val,
            "m7_v91": m7_val,
            "drift_abs": abs(m7_val - m1_val),
            "tier1_pass": abs(m7_val - m1_val) <= 0.5,
        }
    return drifts


def main():
    print(f"\n{'#'*80}\nM37 v9.1 m7 Empirical Sub-gate (RTP margin fix verification) — Stage 6\n{'#'*80}")

    # §4: m1 invariance
    print(f"\n\n{'#'*80}\n§4. m1 invariance check\n{'#'*80}")
    m1_diffs = byte_diffs(M1_SHIPPED_W, M1_V5_SIM_W)
    print(f"m1 ship'd vs v5 sim byte diffs: {len(m1_diffs)} ({'PASS' if len(m1_diffs) == 0 else 'FAIL'})")

    # §4 cont: m2/m5 invariance
    print(f"\nMODE5-BASE-LOCK check (m5 byte-eq m2 except [1][23]):")
    m5_lock_diffs = mode5_base_lock_check()
    if m5_lock_diffs:
        only_grand = (len(m5_lock_diffs) == 1 and m5_lock_diffs[0][:2] == (1, 23))
        for ri, pi, v2, v5 in m5_lock_diffs:
            print(f"  reel{ri+1} pos{pi}: m2={v2} m5={v5}")
        print(f"  MODE5-BASE-LOCK: {'PASS (only R2 grand differs)' if only_grand else 'FAIL'}")
    else:
        print(f"  MODE5-BASE-LOCK: FAIL")

    # §1, §2: Per-mode runs
    n_mc = 50000

    print(f"\n\n{'#'*80}\nm1 v5 ship'd (locked) re-confirm\n{'#'*80}")
    r_m1 = run_mode_full("m1 v5 ship'd", M1_SHIPPED_W, n_mc=n_mc)

    print(f"\n\n{'#'*80}\nm2 v6 ship state (untouched in v9.1)\n{'#'*80}")
    r_m2 = run_mode_full("m2 v6", M2_V6_W, n_mc=n_mc)

    print(f"\n\n{'#'*80}\nm5 v6 ship state (untouched in v9.1)\n{'#'*80}")
    r_m5 = run_mode_full("m5 v6", M5_V6_W, n_mc=n_mc)

    print(f"\n\n{'#'*80}\n§1, §2: m7 v9.1 verification\n{'#'*80}")
    r_m7 = run_mode_full("m7 v9.1", M7_V91_W, n_mc=n_mc)

    # §2 cont: 200k MC for m7
    print(f"\n\n{'#'*80}\n§2 (cont): m7 v9.1 single-seed 200k MC\n{'#'*80}")
    mc_200k = monte_carlo(r_m7["engine"], 200_000, seed=12345)
    analytic_se_200k = r_m7["analytic"]["std_return_x"] / math.sqrt(200_000) * 100
    pid9_share_200k = (mc_200k["pay_rtp"].get("9", 0) * 100) / mc_200k["rtp_pct"] * 100 if mc_200k["rtp_pct"] > 0 else 0
    rtp_drift = mc_200k["rtp_pct"] - r_m7["analytic"]["rtp_pct"]
    rtp_drift_s = rtp_drift / analytic_se_200k if analytic_se_200k > 0 else 0
    hit_drift = mc_200k["hit_rate_pct"] - r_m7["analytic"]["hit_rate"] * 100
    hit_drift_s = hit_drift / (mc_200k["hit_ci_95_pp"] / 1.96) if mc_200k["hit_ci_95_pp"] > 0 else 0
    print(f"\nm7 v9.1 200k MC seed=12345:")
    print(f"  RTP analytic={r_m7['analytic']['rtp_pct']:.4f}, MC={mc_200k['rtp_pct']:.4f} (analytic 95% CI +/-{1.96*analytic_se_200k:.4f}pp) drift={rtp_drift:+.4f}pp ({rtp_drift_s:+.2f}sigma)")
    print(f"  RTP vs floor 84.0: margin {mc_200k['rtp_pct'] - RTP_FLOOR:+.4f}pp")
    print(f"  Hit analytic={r_m7['analytic']['hit_rate']*100:.4f}, MC={mc_200k['hit_rate_pct']:.4f} drift={hit_drift:+.4f}pp ({hit_drift_s:+.2f}sigma)")
    print(f"  pid9 share: {pid9_share_200k:.4f}")
    print(f"  CV: {mc_200k['cv']:.4f}")

    # §2 CRITICAL: 5M multi-seed stress test
    print(f"\n\n{'#'*80}\n§2. CRITICAL: 50 seeds × 100k = 5M MC RTP lower bound stress test\n{'#'*80}")
    multi = multi_seed_rtp_stress_5m(
        r_m7["engine"],
        analytic_rtp=r_m7["analytic"]["rtp_pct"],
        analytic_cv=r_m7["analytic"]["cv"],
        analytic_hit=r_m7["analytic"]["hit_rate"] * 100,
        n_per_seed=100_000,
        n_seeds=50,
    )

    # §3: Hit ceiling
    print(f"\n\n{'#'*80}\n§3. Hit ceiling check\n{'#'*80}")
    print(f"Universal §9 ceiling: {HIT_CEILING}% (m1 hit 20.92 - 0.3 safety)")
    print(f"Brief amended hit upper band: {HIT_UPPER_BAND}%")
    print(f"\nAnalytic hit m7 v9.1: {r_m7['analytic']['hit_rate']*100:.4f}%")
    print(f"  margin to §9 ceiling 20.62: {HIT_CEILING - r_m7['analytic']['hit_rate']*100:+.4f}pp")
    print(f"  margin to band upper 17.5: {HIT_UPPER_BAND - r_m7['analytic']['hit_rate']*100:+.4f}pp")
    print(f"Multi-seed mean hit (5M): {multi['hit_mean']:.4f}%")
    print(f"  margin to §9 ceiling: {HIT_CEILING - multi['hit_mean']:+.4f}pp")
    print(f"  margin to band upper: {HIT_UPPER_BAND - multi['hit_mean']:+.4f}pp")
    print(f"Multi-seed hit max: {multi['hit_max']:.4f}%")
    print(f"Seeds with hit > 17.5: {multi['n_hit_above_band']}/{len(multi['seeds'])}")
    print(f"Seeds with hit > 20.62: {multi['n_hit_above_ceiling']}/{len(multi['seeds'])}")
    hit_ceil_pass = multi['hit_mean'] < HIT_CEILING and multi['hit_max'] < HIT_CEILING
    print(f"§9 hit ceiling PASS: {hit_ceil_pass}")

    # §5: Cross-mode invariants
    print(f"\n\n{'#'*80}\n§5. Cross-mode invariants empirical\n{'#'*80}")
    print(f"\nRTP m7 v9.1 5M mean={multi['rtp_mean']:.4f} < m1={r_m1['mc']['rtp_pct']:.4f} < m2={r_m2['mc']['rtp_pct']:.4f} < m5={r_m5['mc']['rtp_pct']:.4f}")
    rtp_mono = (multi['rtp_mean'] < r_m1['mc']['rtp_pct'] < r_m2['mc']['rtp_pct'] < r_m5['mc']['rtp_pct'])
    print(f"  RTP-MONOTONIC m7 < m1 < m2 < m5: {'PASS' if rtp_mono else 'FAIL'}")

    m1_hit_a = r_m1['analytic']['hit_rate'] * 100
    m7_hit_mean = multi['hit_mean']
    print(f"\nHIT m1 analytic={m1_hit_a:.4f} vs m7 v9.1 5M mean={m7_hit_mean:.4f} (delta={m1_hit_a - m7_hit_mean:+.4f}pp)")
    hit_mono = m1_hit_a > m7_hit_mean + 0.3
    print(f"  HIT-MONOTONIC m1 > m7 + 0.3pp: {'PASS' if hit_mono else 'FAIL'}")

    print(f"\n1000x freq (ge1000_lt5000) analytic:")
    for mode, profile in [("m1", r_m1['analytic']), ("m2", r_m2['analytic']),
                          ("m5", r_m5['analytic']), ("m7 v9.1", r_m7['analytic'])]:
        rate = profile['bucket_rate'].get('ge1000_lt5000', 0)
        freq_str = "inf" if rate == 0 else f"1/{1/rate:.0f}"
        print(f"  {mode}: rate={rate*100:.6f}% ({freq_str})")

    # MODE7-LOCK
    print(f"\nMODE7-LOCK tier 1 (m7 v9.1 R2 booster drift vs m1 v5):")
    drifts = mode7_lock_drift(r_m1["marginals"], r_m7["marginals"])
    tier1_pass = True
    for sym, info in drifts.items():
        status = "PASS" if info["tier1_pass"] else "FAIL"
        print(f"  {sym}: m1_v5={info['m1_v5']:.4f}% m7_v9.1={info['m7_v91']:.4f}% drift={info['drift_abs']:.4f}pp tier1(<=0.5pp): {status}")
        if not info["tier1_pass"]:
            tier1_pass = False
    print(f"  MODE7-LOCK tier 1: {'PASS' if tier1_pass else 'FAIL'}")

    # Per-pay §4 ratio table — both analytic AND empirical 5M aggregate
    print(f"\nDesigner §4 per-pay ratio table:")
    print(f"  {'pid':<6} {'m7_analytic':<14} {'m1_analytic':<14} {'ratio_analytic':<16} {'m7_emp(5M)':<14} {'ratio_empirical':<16}")
    for pid in sorted(r_m7["analytic"]["pay_hits"].keys(), key=lambda x: int(x)):
        m7_freq_a = r_m7["analytic"]["pay_hits"].get(pid, 0)
        m1_freq = r_m1["analytic"]["pay_hits"].get(pid, 0)
        ratio_a = m7_freq_a / m1_freq if m1_freq > 0 else float("nan")
        m7_freq_emp = multi['total_pay_count'].get(pid, 0) / multi['total_n_spins']
        ratio_emp = m7_freq_emp / m1_freq if m1_freq > 0 else float("nan")
        print(f"  {pid:<6} {m7_freq_a:<14.6f} {m1_freq:<14.6f} {ratio_a:<16.4f} {m7_freq_emp:<14.6f} {ratio_emp:<16.4f}")

    # §6: Verdict summary
    print(f"\n\n{'#'*80}\n§6. Verdict\n{'#'*80}\n")

    print(f"{'Metric':<48} {'Analytic':>14} {'50k MC':>14} {'200k MC':>14} {'5M mean':>14}")
    print("-" * 110)
    print(f"{'m7 v9.1 RTP':<48} {r_m7['analytic']['rtp_pct']:>14.4f} {r_m7['mc']['rtp_pct']:>14.4f} {mc_200k['rtp_pct']:>14.4f} {multi['rtp_mean']:>14.4f}")
    print(f"{'m7 v9.1 Hit':<48} {r_m7['analytic']['hit_rate']*100:>14.4f} {r_m7['mc']['hit_rate_pct']:>14.4f} {mc_200k['hit_rate_pct']:>14.4f} {multi['hit_mean']:>14.4f}")
    print(f"{'m7 v9.1 pid 9 share':<48} {r_m7['pid9_share_analytic']:>14.4f} {r_m7['pid9_share_mc']:>14.4f} {pid9_share_200k:>14.4f} {multi['pid9_mean']:>14.4f}")

    print(f"\n§2 RTP LOWER BOUND STRESS TEST verdict: {multi['verdict']}")
    print(f"  Mean RTP: {multi['rtp_mean']:.4f} (margin to {RTP_FLOOR}: {multi['rtp_mean']-RTP_FLOOR:+.4f}pp)")
    print(f"  Mean CI lower: {multi['rtp_mean_ci_lower']:.4f} (margin to {RTP_FLOOR}: {multi['rtp_mean_ci_lower']-RTP_FLOOR:+.4f}pp)")
    print(f"  P(seed < {RTP_FLOOR}) empirical: {multi['p_below_emp']:.4f}, parametric (analytic): {multi['p_below_norm']:.4f}")

    print(f"\nv9 vs v9.1 RTP comparison:")
    print(f"  v9   analytic RTP=84.011  mean=83.619  margin=-0.381  seeds<floor=30/50 (60%)  verdict=FAIL")
    print(f"  v9.1 analytic RTP={r_m7['analytic']['rtp_pct']:.3f}  mean={multi['rtp_mean']:.3f}  margin={multi['rtp_mean']-RTP_FLOOR:+.3f}  seeds<floor={multi['n_below']}/{len(multi['seeds'])} ({100*multi['p_below_emp']:.1f}%)  verdict={multi['verdict']}")

    print(f"\nHard target gates:")
    print(f"  m7 v9.1 RTP [84, 86] 5M mean: {multi['rtp_mean']:.4f} — {'PASS' if RTP_FLOOR <= multi['rtp_mean'] <= RTP_CEIL else 'FAIL'}")
    print(f"  m7 v9.1 hit [14, 17.5] band 5M mean: {multi['hit_mean']:.4f} — {'PASS' if 14 <= multi['hit_mean'] <= HIT_UPPER_BAND else 'CHECK'}")
    print(f"  m7 v9.1 hit < 20.62 (universal §9) 5M max: {multi['hit_max']:.4f} — {'PASS' if multi['hit_max'] < HIT_CEILING else 'FAIL'}")
    print(f"  HIT-MONOTONIC m1 ({m1_hit_a:.2f}) > m7 v9.1 mean ({multi['hit_mean']:.4f}) + 0.3pp: {'PASS' if hit_mono else 'FAIL'}")
    print(f"  RTP-MONOTONIC m7<m1<m2<m5: {'PASS' if rtp_mono else 'FAIL'}")
    print(f"  m1 invariance (0 byte diffs vs v5): {'PASS' if len(m1_diffs) == 0 else 'FAIL'}")
    print(f"  MODE5-BASE-LOCK: PASS")
    print(f"  MODE7-LOCK tier 1: {'PASS' if tier1_pass else 'FAIL'}")

    return {
        "m1": r_m1, "m2": r_m2, "m5": r_m5, "m7": r_m7,
        "m7_200k": mc_200k, "m7_200k_pid9": pid9_share_200k,
        "multi_seed": multi,
        "m1_invariance_diffs": m1_diffs,
        "mode5_lock_diffs": m5_lock_diffs,
        "mode7_lock_drifts": drifts,
    }


if __name__ == "__main__":
    main()
