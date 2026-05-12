"""v5 empirical sub-gate — Stage 6 verification.

1. Load v5 m1 + m7 weights from session_artifacts/M37/v5_sim_weights/
2. Run analytic_profile() and verify match vs design_v5.md predictions
3. Run Monte Carlo simulation (50k+ spins per mode) and verify analytic vs empirical
4. Cross-mode invariants check (m1/m7 vs m2/m5 from current machine weights)
5. Dump full 12-section style baseline metrics

Usage:
    python empirical_v5_subgate.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    analytic_profile,
    compute_reel_marginal,
    multiplier_to_bucket,
)
from slot_designer.core.engine.loader import load_engine

SPEC = ROOT / "slot_designer" / "machines" / "M37" / "spec.json"

# v5 sim weight files
V5_BASE = ROOT / "session_artifacts" / "M37" / "v5_sim_weights"
M1_V5_W = V5_BASE / "mode_1" / "weights.json"
M7_V5_W = V5_BASE / "mode_7" / "weights.json"

# Baseline machine weights (m2, m5 untouched — direct reference)
M2_BASE_W = ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_2" / "weights.json"
M5_BASE_W = ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_5" / "weights.json"

# Baseline m1, m7 for comparison
M1_BASE_W = ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_1" / "weights.json"
M7_BASE_W = ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_7" / "weights.json"


# -----------------------------------------------------------------------------
# Monte Carlo (in-memory) — uses SpinEngine.spin()
# -----------------------------------------------------------------------------

# Buckets matching analyzer / analytic_rtp
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
    """Run n_spins Monte Carlo spins. Returns metrics dict."""
    rng = Random(seed)

    total_mult = 0.0
    total_mult_sq = 0.0
    n_hits = 0
    bucket_count: dict[str, int] = defaultdict(int)
    bucket_rtp: dict[str, float] = defaultdict(float)
    pay_count: dict[str, int] = defaultdict(int)
    pay_rtp: dict[str, float] = defaultdict(float)

    # pid 9 sub-pay breakdown (mult tally)
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
            pay_rtp[pid] += mult
            if pid == "9":
                pid9_mult_count[mult] += 1
            bkt = bucket_for(mult)
            if bkt is not None:
                bucket_count[bkt] += 1
                bucket_rtp[bkt] += mult

    rtp_pct = (total_mult / n_spins) * 100
    hit_rate = n_hits / n_spins
    # Variance/CV on per-spin mult
    mean_mult = total_mult / n_spins
    var = max(0.0, (total_mult_sq / n_spins) - mean_mult * mean_mult)
    std_return_x = math.sqrt(var)
    cv = std_return_x / mean_mult if mean_mult > 0 else 0.0

    # 95% CI for RTP (using normal approximation): 1.96 * stderr
    rtp_stderr = std_return_x / math.sqrt(n_spins) * 100
    rtp_ci_95 = 1.96 * rtp_stderr

    # 95% CI for hit_rate (Wald): 1.96 * sqrt(p*(1-p)/n)
    hit_stderr = math.sqrt(hit_rate * (1 - hit_rate) / n_spins)
    hit_ci_95 = 1.96 * hit_stderr * 100  # convert to pp

    return {
        "n_spins": n_spins,
        "rtp_pct": rtp_pct,
        "rtp_ci_95_pp": rtp_ci_95,
        "hit_rate_pct": hit_rate * 100,
        "hit_ci_95_pp": hit_ci_95,
        "cv": cv,
        "std_return_x": std_return_x,
        "bucket_count": dict(bucket_count),
        "bucket_rate": {k: v / n_spins for k, v in bucket_count.items()},
        "bucket_rtp": {k: v / n_spins for k, v in bucket_rtp.items()},
        "pay_count": dict(pay_count),
        "pay_hits": {k: v / n_spins for k, v in pay_count.items()},
        "pay_rtp": {k: v / n_spins for k, v in pay_rtp.items()},
        "pid9_mult_breakdown": {
            f"mult_{m}": {
                "count": c,
                "rate": c / n_spins,
                "rtp_pp": (m * c / n_spins) * 100,
            }
            for m, c in sorted(pid9_mult_count.items())
        },
    }


STRIPS = ROOT / "slot_designer" / "machines" / "M37" / "reel_strips.json"


def analytic_summary(weights_path: Path) -> dict:
    engine, _ = load_engine(SPEC, weights_path, strips_path=STRIPS)
    profile = analytic_profile(engine)
    marginals = [compute_reel_marginal(r) for r in engine.reels]
    return {
        "profile": profile,
        "marginals": marginals,
        "engine": engine,
    }


def fmt_marginals(marginals: list[dict[str, float]]) -> str:
    """Pretty-print per-reel marginals."""
    BAR_SYMS = ("1bar", "2bar", "3bar", "7bar")
    out = []
    syms = ["blank", "1bar", "2bar", "3bar", "7bar", "high7", "wild", "mini", "minor", "major", "grand"]
    for i, m in enumerate(marginals):
        bar_sum = sum(m.get(s, 0) for s in BAR_SYMS) * 100
        line = f"R{i+1}: "
        for s in syms:
            v = m.get(s, 0) * 100
            if v > 0.001:
                line += f"{s}={v:.2f} "
        out.append(line + f"[bar_sum={bar_sum:.2f}]")
    return "\n".join(out)


def diff_pct(a: float, b: float) -> float:
    """Absolute pp difference. For RTP/marginal pct values."""
    return abs(a - b)


def run_mode(mode_label: str, weights_path: Path, n_mc: int = 50000) -> dict:
    print(f"\n{'='*80}\n{mode_label}: {weights_path}\n{'='*80}")
    a = analytic_summary(weights_path)
    profile = a["profile"]
    marginals = a["marginals"]
    engine = a["engine"]

    print(f"\nAnalytic RTP: {profile['rtp_pct']:.4f}%")
    print(f"Analytic Hit: {profile['hit_rate']*100:.4f}%")
    print(f"Analytic CV: {profile['cv']:.4f}")
    print(f"Analytic std_return_x: {profile['std_return_x']:.4f}")
    print(f"Total prob: {profile['total_prob']:.10f}")
    print(f"P(reroll-blocked): {profile['p_reroll_blocked']:.6f}")

    print(f"\nMarginals (post-reroll on R1/R2/R3 — note: analytic uses raw marginals; reroll only kicks in for combo):")
    print(fmt_marginals(marginals))

    print(f"\nAnalytic per-pay_id RTP-pp:")
    for pid in sorted(profile["pay_rtp"].keys(), key=lambda x: int(x)):
        rtp_pp = profile["pay_rtp"][pid] * 100
        hit_pp = profile["pay_hits"][pid] * 100
        print(f"  pid {pid}: RTP-pp={rtp_pp:.4f}, hit-pp={hit_pp:.4f}")

    print(f"\nAnalytic bucket distribution:")
    for bkt in ["ge1_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt50", "ge50_lt100",
                "ge100_lt200", "ge200_lt500", "ge500_lt1000", "ge1000_lt5000", "ge5000"]:
        rate = profile["bucket_rate"].get(bkt, 0)
        rtp_pp = profile["bucket_rtp"].get(bkt, 0) * 100
        print(f"  {bkt}: rate={rate*100:.4f}%, rtp-pp={rtp_pp:.4f}, 1/freq={'inf' if rate==0 else f'1/{1/rate:.1f}'}")

    pid9_share = (profile["pay_rtp"].get("9", 0) * 100) / profile["rtp_pct"] * 100 if profile["rtp_pct"] > 0 else 0
    print(f"\nAnalytic pid 9 RTP / total RTP share: {pid9_share:.4f}%")

    # Monte Carlo
    print(f"\nRunning Monte Carlo {n_mc:,} spins...")
    mc = monte_carlo(engine, n_mc)
    print(f"\nMC RTP: {mc['rtp_pct']:.4f}% (±{mc['rtp_ci_95_pp']:.4f} 95% CI)")
    print(f"MC Hit: {mc['hit_rate_pct']:.4f}% (±{mc['hit_ci_95_pp']:.4f} 95% CI)")
    print(f"MC CV: {mc['cv']:.4f}")
    print(f"MC std_return_x: {mc['std_return_x']:.4f}")

    print(f"\nMC vs Analytic drift:")
    rtp_drift = mc['rtp_pct'] - profile['rtp_pct']
    rtp_drift_sigma = rtp_drift / (mc['rtp_ci_95_pp'] / 1.96) if mc['rtp_ci_95_pp'] > 0 else 0
    hit_drift = mc['hit_rate_pct'] - profile['hit_rate']*100
    hit_drift_sigma = hit_drift / (mc['hit_ci_95_pp'] / 1.96) if mc['hit_ci_95_pp'] > 0 else 0
    print(f"  RTP drift: {rtp_drift:+.4f}pp ({rtp_drift_sigma:+.2f}σ)")
    print(f"  Hit drift: {hit_drift:+.4f}pp ({hit_drift_sigma:+.2f}σ)")

    print(f"\nMC per-pay_id breakdown:")
    for pid in sorted(mc["pay_rtp"].keys(), key=lambda x: int(x)):
        rtp_pp = mc["pay_rtp"][pid] * 100
        hit_pp = mc["pay_hits"][pid] * 100
        analytic_rtp_pp = profile["pay_rtp"].get(pid, 0) * 100
        drift = rtp_pp - analytic_rtp_pp
        print(f"  pid {pid}: MC rtp-pp={rtp_pp:.4f} hit-pp={hit_pp:.4f} | analytic={analytic_rtp_pp:.4f} drift={drift:+.4f}")

    pid9_share_mc = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0
    print(f"\nMC pid 9 share: {pid9_share_mc:.4f}% (analytic: {pid9_share:.4f}%, drift: {pid9_share_mc - pid9_share:+.4f}pp)")

    print(f"\nMC pid 9 sub-mult breakdown:")
    for k, info in mc["pid9_mult_breakdown"].items():
        print(f"  {k}: count={info['count']:,} rate={info['rate']*100:.4f}% rtp-pp={info['rtp_pp']:.4f}")

    print(f"\nMC bucket distribution:")
    for bkt in ["ge1_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt50", "ge50_lt100",
                "ge100_lt200", "ge200_lt500", "ge500_lt1000", "ge1000_lt5000", "ge5000"]:
        rate = mc["bucket_rate"].get(bkt, 0)
        rtp_pp = mc["bucket_rtp"].get(bkt, 0) * 100
        cnt = mc["bucket_count"].get(bkt, 0)
        analytic_rate = profile["bucket_rate"].get(bkt, 0)
        rate_drift_pp = (rate - analytic_rate) * 100
        analytic_rtp = profile["bucket_rtp"].get(bkt, 0) * 100
        rtp_drift = rtp_pp - analytic_rtp
        freq_str = "inf" if rate == 0 else f"1/{1/rate:.0f}"
        print(f"  {bkt}: cnt={cnt:,} rate={rate*100:.4f}% rtp-pp={rtp_pp:.4f} 1/freq={freq_str} | analytic={analytic_rate*100:.4f}% drift={rate_drift_pp:+.4f}pp")

    return {"analytic": profile, "mc": mc, "marginals": marginals, "engine": engine,
            "pid9_share_analytic": pid9_share, "pid9_share_mc": pid9_share_mc}


def main():
    print(f"\n{'#'*80}\nM37 v5 Empirical Sub-gate — Stage 6\n{'#'*80}")
    print(f"\nRunning analytic + Monte Carlo for v5 m1, v5 m7, baseline m2, baseline m5")

    n_mc = 50000

    r_m1 = run_mode("v5 mode 1", M1_V5_W, n_mc=n_mc)
    r_m7 = run_mode("v5 mode 7", M7_V5_W, n_mc=n_mc)

    # Cross-mode reference: m2, m5 (unchanged)
    print(f"\n\n{'#'*80}\nReference: baseline m2 + m5 (untouched, locked per v5 brief)\n{'#'*80}")
    r_m2 = run_mode("baseline mode 2", M2_BASE_W, n_mc=n_mc)
    r_m5 = run_mode("baseline mode 5", M5_BASE_W, n_mc=n_mc)

    # Cross-mode invariants
    print(f"\n\n{'#'*80}\nCross-mode invariants check\n{'#'*80}")
    print(f"\nRTP m7={r_m7['mc']['rtp_pct']:.4f} < m1={r_m1['mc']['rtp_pct']:.4f} < m2={r_m2['mc']['rtp_pct']:.4f} < m5={r_m5['mc']['rtp_pct']:.4f}")
    rtp_mono = (r_m7['mc']['rtp_pct'] < r_m1['mc']['rtp_pct'] < r_m2['mc']['rtp_pct'] < r_m5['mc']['rtp_pct'])
    print(f"  RTP-MONOTONIC m7 < m1 < m2 < m5: {'PASS' if rtp_mono else 'FAIL'}")

    print(f"\nHIT m1={r_m1['mc']['hit_rate_pct']:.4f} vs m7={r_m7['mc']['hit_rate_pct']:.4f} (delta={r_m1['mc']['hit_rate_pct']-r_m7['mc']['hit_rate_pct']:.4f}pp)")
    hit_mono = (r_m1['mc']['hit_rate_pct'] > r_m7['mc']['hit_rate_pct'] + 0.3)
    print(f"  HIT-MONOTONIC m1 > m7 + 0.3pp: {'PASS' if hit_mono else 'FAIL'}")

    # 1000× freq across modes (bucket ge1000_lt5000)
    print(f"\n1000× freq (ge1000_lt5000):")
    for mode, r in [("m1", r_m1), ("m2", r_m2), ("m5", r_m5), ("m7", r_m7)]:
        rate = r['mc']['bucket_rate'].get('ge1000_lt5000', 0)
        freq_str = "inf" if rate == 0 else f"1/{1/rate:.0f}"
        print(f"  {mode}: rate={rate*100:.6f}% ({freq_str})")
    r1000_m1 = r_m1['mc']['bucket_rate'].get('ge1000_lt5000', 0)
    r1000_m2 = r_m2['mc']['bucket_rate'].get('ge1000_lt5000', 0)
    r1000_m5 = r_m5['mc']['bucket_rate'].get('ge1000_lt5000', 0)
    freq_mono = (r1000_m1 < r1000_m2 < r1000_m5)
    print(f"  1000× freq m1 < m2 < m5: {'PASS' if freq_mono else 'FAIL'}")

    # Summary table
    print(f"\n\n{'#'*80}\nSummary\n{'#'*80}\n")
    print(f"{'Metric':<40} {'v5 m1 analytic':>16} {'v5 m1 MC':>16} {'v5 m7 analytic':>16} {'v5 m7 MC':>16}")
    print("-" * 110)
    print(f"{'RTP %':<40} {r_m1['analytic']['rtp_pct']:>16.4f} {r_m1['mc']['rtp_pct']:>16.4f} {r_m7['analytic']['rtp_pct']:>16.4f} {r_m7['mc']['rtp_pct']:>16.4f}")
    print(f"{'Hit %':<40} {r_m1['analytic']['hit_rate']*100:>16.4f} {r_m1['mc']['hit_rate_pct']:>16.4f} {r_m7['analytic']['hit_rate']*100:>16.4f} {r_m7['mc']['hit_rate_pct']:>16.4f}")
    print(f"{'CV':<40} {r_m1['analytic']['cv']:>16.4f} {r_m1['mc']['cv']:>16.4f} {r_m7['analytic']['cv']:>16.4f} {r_m7['mc']['cv']:>16.4f}")
    print(f"{'pid 9 share %':<40} {r_m1['pid9_share_analytic']:>16.4f} {r_m1['pid9_share_mc']:>16.4f} {r_m7['pid9_share_analytic']:>16.4f} {r_m7['pid9_share_mc']:>16.4f}")

    print(f"\nv5 m1 hard target gates:")
    print(f"  pid9 share [19, 21]: {r_m1['pid9_share_mc']:.2f} {'PASS' if 19 <= r_m1['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  pid9 share empirical band [18.5, 21.5]: {'PASS' if 18.5 <= r_m1['pid9_share_mc'] <= 21.5 else 'FAIL'}")
    print(f"  RTP [94, 96]: {r_m1['mc']['rtp_pct']:.2f} {'PASS' if 94 <= r_m1['mc']['rtp_pct'] <= 96 else 'FAIL'}")
    print(f"  HIT-MONOTONIC m1 > m7 + 0.3: {'PASS' if hit_mono else 'FAIL'}")

    return {"m1": r_m1, "m7": r_m7, "m2": r_m2, "m5": r_m5}


if __name__ == "__main__":
    main()
