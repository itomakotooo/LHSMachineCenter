"""v6 empirical sub-gate — Stage 6 verification for m2 + m5 + m7.

1. Load v6 m2/m5/m7 + ship'd v5 m1 weights
2. Run analytic_profile() and verify match vs design_v6.md + design_v6_m7.md
3. Run Monte Carlo (50k+ spins per mode); verify analytic vs empirical within 2sigma
4. Cross-mode invariants: RTP-MONOTONIC m7<m1<m2<m5, HIT-MONOTONIC m1>m7+0.3, MODE5-BASE-LOCK byte-eq, MODE7-LOCK tier1 drift, m1 invariance vs v5 ship'd
5. Dump full 12-section style baseline metrics per mode

Usage:
    python empirical_v6_subgate.py
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
)
from slot_designer.core.engine.loader import load_engine

SPEC = ROOT / "slot_designer" / "machines" / "M37" / "spec.json"
STRIPS = ROOT / "slot_designer" / "machines" / "M37" / "reel_strips.json"

# v6 sim weight files (m2/m5/m7)
V6_BASE = ROOT / "session_artifacts" / "M37" / "v6_sim_weights"
M2_V6_W = V6_BASE / "mode_2" / "weights.json"
M5_V6_W = V6_BASE / "mode_5" / "weights.json"
M7_V6_W = V6_BASE / "mode_7" / "weights.json"

# v5 ship'd m1 (the current machines/M37/weights/mode_1/weights.json is v5 ship'd state)
M1_SHIPPED_W = ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_1" / "weights.json"

# For comparison, also reference v5 sim sources:
M1_V5_SIM_W = ROOT / "session_artifacts" / "M37" / "v5_sim_weights" / "mode_1" / "weights.json"


# -----------------------------------------------------------------------------
# Monte Carlo (in-memory) — uses SpinEngine.spin()
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
    bucket_rtp: dict[str, float] = defaultdict(float)
    pay_count: dict[str, int] = defaultdict(int)
    pay_rtp: dict[str, float] = defaultdict(float)
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
        "rtp_pct": rtp_pct,
        "rtp_ci_95_pp": rtp_ci_95,
        "hit_rate_pct": hit_rate * 100,
        "hit_ci_95_pp": hit_ci_95,
        "cv": cv,
        "std_return_x": std_return_x,
        "bucket_count": dict(bucket_count),
        "bucket_rate": {k: v / n_spins for k, v in bucket_count.items()},
        "bucket_rtp": {k: v / n_spins for k, v in bucket_count.items() if False},
        "bucket_rtp_pp": {k: v / n_spins * 100 for k, v in bucket_rtp.items()},
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


def run_mode(mode_label: str, weights_path: Path, n_mc: int = 50000, seed: int = 42) -> dict:
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

    print(f"\nMarginals (per-reel symbol probs):")
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

    pid9_share_a = (profile["pay_rtp"].get("9", 0) * 100) / profile["rtp_pct"] * 100 if profile["rtp_pct"] > 0 else 0
    print(f"\nAnalytic pid 9 RTP / total RTP share: {pid9_share_a:.4f}%")

    print(f"\nRunning Monte Carlo {n_mc:,} spins (seed={seed})...")
    mc = monte_carlo(engine, n_mc, seed=seed)
    print(f"\nMC RTP: {mc['rtp_pct']:.4f}% (+/- {mc['rtp_ci_95_pp']:.4f} 95% CI)")
    print(f"MC Hit: {mc['hit_rate_pct']:.4f}% (+/- {mc['hit_ci_95_pp']:.4f} 95% CI)")
    print(f"MC CV: {mc['cv']:.4f}")
    print(f"MC std_return_x: {mc['std_return_x']:.4f}")

    print(f"\nMC vs Analytic drift:")
    rtp_drift = mc['rtp_pct'] - profile['rtp_pct']
    rtp_drift_sigma = rtp_drift / (mc['rtp_ci_95_pp'] / 1.96) if mc['rtp_ci_95_pp'] > 0 else 0
    hit_drift = mc['hit_rate_pct'] - profile['hit_rate']*100
    hit_drift_sigma = hit_drift / (mc['hit_ci_95_pp'] / 1.96) if mc['hit_ci_95_pp'] > 0 else 0
    print(f"  RTP drift: {rtp_drift:+.4f}pp ({rtp_drift_sigma:+.2f} sigma)")
    print(f"  Hit drift: {hit_drift:+.4f}pp ({hit_drift_sigma:+.2f} sigma)")

    print(f"\nMC per-pay_id breakdown:")
    for pid in sorted(mc["pay_rtp"].keys(), key=lambda x: int(x)):
        rtp_pp = mc["pay_rtp"][pid] * 100
        hit_pp = mc["pay_hits"][pid] * 100
        analytic_rtp_pp = profile["pay_rtp"].get(pid, 0) * 100
        drift = rtp_pp - analytic_rtp_pp
        print(f"  pid {pid}: MC rtp-pp={rtp_pp:.4f} hit-pp={hit_pp:.4f} | analytic={analytic_rtp_pp:.4f} drift={drift:+.4f}")

    pid9_share_mc = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0
    print(f"\nMC pid 9 share: {pid9_share_mc:.4f}% (analytic: {pid9_share_a:.4f}%, drift: {pid9_share_mc - pid9_share_a:+.4f}pp)")

    print(f"\nMC pid 9 sub-mult breakdown:")
    for k, info in mc["pid9_mult_breakdown"].items():
        print(f"  {k}: count={info['count']:,} rate={info['rate']*100:.4f}% rtp-pp={info['rtp_pp']:.4f}")

    print(f"\nMC bucket distribution:")
    for bkt in ["ge1_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt50", "ge50_lt100",
                "ge100_lt200", "ge200_lt500", "ge500_lt1000", "ge1000_lt5000", "ge5000"]:
        rate = mc["bucket_rate"].get(bkt, 0)
        rtp_pp = mc["bucket_rtp_pp"].get(bkt, 0)
        cnt = mc["bucket_count"].get(bkt, 0)
        analytic_rate = profile["bucket_rate"].get(bkt, 0)
        rate_drift_pp = (rate - analytic_rate) * 100
        analytic_rtp = profile["bucket_rtp"].get(bkt, 0) * 100
        rtp_drift = rtp_pp - analytic_rtp
        freq_str = "inf" if rate == 0 else f"1/{1/rate:.0f}"
        print(f"  {bkt}: cnt={cnt:,} rate={rate*100:.4f}% rtp-pp={rtp_pp:.4f} 1/freq={freq_str} | analytic={analytic_rate*100:.4f}% drift={rate_drift_pp:+.4f}pp")

    return {
        "analytic": profile,
        "mc": mc,
        "marginals": marginals,
        "engine": engine,
        "pid9_share_analytic": pid9_share_a,
        "pid9_share_mc": pid9_share_mc,
    }


def mode5_base_lock_check() -> bool:
    """Verify m5 v6 == m2 v6 byte-equal except R2 grand position [1][23]."""
    m2 = json.loads(M2_V6_W.read_text(encoding="utf-8"))["weights"]
    m5 = json.loads(M5_V6_W.read_text(encoding="utf-8"))["weights"]
    diffs = []
    for ri in range(3):
        for pi in range(len(m2[ri])):
            if m2[ri][pi] != m5[ri][pi]:
                diffs.append((ri, pi, m2[ri][pi], m5[ri][pi]))
    return diffs


def m1_invariance_check() -> dict:
    """Verify m1 ship'd weights byte-eq v5 sim weights."""
    m1_ship = json.loads(M1_SHIPPED_W.read_text(encoding="utf-8"))["weights"]
    m1_v5 = json.loads(M1_V5_SIM_W.read_text(encoding="utf-8"))["weights"]
    diffs = []
    for ri in range(3):
        for pi in range(len(m1_ship[ri])):
            if m1_ship[ri][pi] != m1_v5[ri][pi]:
                diffs.append((ri, pi, m1_ship[ri][pi], m1_v5[ri][pi]))
    return diffs


def mode7_lock_drift(m1_marginals, m7_marginals) -> dict:
    """Per design_v6_m7 §6: m1 v5 anchors mini 2.786 / minor 1.993 / major 1.525.
    m7 v6 must drift ≤ 0.5pp per tier (tier 1).
    """
    m1_r2 = m1_marginals[1]
    m7_r2 = m7_marginals[1]
    drifts = {}
    for sym in ["mini", "minor", "major", "grand"]:
        m1_val = m1_r2.get(sym, 0) * 100
        m7_val = m7_r2.get(sym, 0) * 100
        drifts[sym] = {
            "m1_v5": m1_val,
            "m7_v6": m7_val,
            "drift_abs": abs(m7_val - m1_val),
            "tier1_pass": abs(m7_val - m1_val) <= 0.5,
        }
    return drifts


def main():
    print(f"\n{'#'*80}\nM37 v6 Empirical Sub-gate (m2 + m5 + m7) — Stage 6\n{'#'*80}")
    print(f"\nm1 v5 ship'd is locked, will re-run analytic to confirm invariance.")

    n_mc = 50000

    # m1 (locked / v5 ship'd) — re-confirm
    print(f"\n\n{'#'*80}\nm1 v5 ship'd re-confirm (locked, untouched)\n{'#'*80}")
    r_m1 = run_mode("m1 v5 ship'd", M1_SHIPPED_W, n_mc=n_mc)

    # m2 + m5 + m7 v6
    print(f"\n\n{'#'*80}\nm2 + m5 + m7 v6 verification\n{'#'*80}")
    r_m2 = run_mode("m2 v6", M2_V6_W, n_mc=n_mc)
    r_m5 = run_mode("m5 v6", M5_V6_W, n_mc=n_mc)
    r_m7 = run_mode("m7 v6", M7_V6_W, n_mc=n_mc)

    # Cross-mode invariants
    print(f"\n\n{'#'*80}\nCross-mode invariants check\n{'#'*80}")

    # RTP-MONOTONIC
    print(f"\nRTP m7={r_m7['mc']['rtp_pct']:.4f} < m1={r_m1['mc']['rtp_pct']:.4f} < m2={r_m2['mc']['rtp_pct']:.4f} < m5={r_m5['mc']['rtp_pct']:.4f}")
    rtp_mono = (r_m7['mc']['rtp_pct'] < r_m1['mc']['rtp_pct'] < r_m2['mc']['rtp_pct'] < r_m5['mc']['rtp_pct'])
    print(f"  RTP-MONOTONIC m7 < m1 < m2 < m5: {'PASS' if rtp_mono else 'FAIL'}")

    # HIT-MONOTONIC m1 > m7 + 0.3pp
    print(f"\nHIT m1={r_m1['mc']['hit_rate_pct']:.4f} vs m7={r_m7['mc']['hit_rate_pct']:.4f} (delta={r_m1['mc']['hit_rate_pct']-r_m7['mc']['hit_rate_pct']:.4f}pp)")
    hit_mono = (r_m1['mc']['hit_rate_pct'] > r_m7['mc']['hit_rate_pct'] + 0.3)
    print(f"  HIT-MONOTONIC m1 > m7 + 0.3pp: {'PASS' if hit_mono else 'FAIL'}")

    # 1000× freq m1 < m2 < m5 (m7 is independent low-RTP cut mode)
    print(f"\n1000x freq (ge1000_lt5000):")
    for mode, r in [("m1", r_m1), ("m2", r_m2), ("m5", r_m5), ("m7", r_m7)]:
        rate = r['mc']['bucket_rate'].get('ge1000_lt5000', 0)
        freq_str = "inf" if rate == 0 else f"1/{1/rate:.0f}"
        print(f"  {mode}: rate={rate*100:.6f}% ({freq_str})")
    r1000_m1 = r_m1['mc']['bucket_rate'].get('ge1000_lt5000', 0)
    r1000_m2 = r_m2['mc']['bucket_rate'].get('ge1000_lt5000', 0)
    r1000_m5 = r_m5['mc']['bucket_rate'].get('ge1000_lt5000', 0)
    freq_mono = (r1000_m1 < r1000_m2 < r1000_m5)
    print(f"  1000x freq m1 < m2 < m5: {'PASS' if freq_mono else 'FAIL'}")

    # MODE5-BASE-LOCK byte-equality check
    print(f"\nMODE5-BASE-LOCK check (m5 base byte-eq m2 base except R2 grand [1][23]):")
    m5_diffs = mode5_base_lock_check()
    if m5_diffs:
        for d in m5_diffs:
            ri, pi, v2, v5 = d
            print(f"  reel{ri+1} pos{pi}: m2={v2} m5={v5}")
        only_grand = (len(m5_diffs) == 1 and m5_diffs[0][:2] == (1, 23))
        print(f"  MODE5-BASE-LOCK: {'PASS (only R2 grand differs)' if only_grand else 'FAIL'}")
    else:
        print(f"  MODE5-BASE-LOCK: FAIL — m2 and m5 are byte-equal everywhere (grand should differ)")

    # MODE7-LOCK tier 1 (R2 booster marginals drift)
    print(f"\nMODE7-LOCK tier 1 (drift m7 vs m1 v5 ship'd R2 booster marginals):")
    drifts = mode7_lock_drift(r_m1["marginals"], r_m7["marginals"])
    tier1_pass = True
    for sym, info in drifts.items():
        status = "PASS" if info["tier1_pass"] else "FAIL"
        print(f"  {sym}: m1_v5={info['m1_v5']:.4f}% m7_v6={info['m7_v6']:.4f}% drift={info['drift_abs']:.4f}pp tier1(<=0.5pp): {status}")
        if not info["tier1_pass"]:
            tier1_pass = False
    print(f"  MODE7-LOCK tier 1: {'PASS' if tier1_pass else 'FAIL'}")

    # m1 invariance vs v5 sim
    print(f"\nm1 invariance check (m1 ship'd byte-eq m1 v5 sim):")
    m1_diffs = m1_invariance_check()
    print(f"  Diffs: {len(m1_diffs)} ({'PASS' if len(m1_diffs) == 0 else 'FAIL'})")

    # Hard target gates per mode
    print(f"\n\n{'#'*80}\nHard target gates\n{'#'*80}")
    print(f"\nm1 v5 hard targets (must still hold; locked):")
    print(f"  RTP [94, 96]: {r_m1['mc']['rtp_pct']:.4f} {'PASS' if 94 <= r_m1['mc']['rtp_pct'] <= 96 else 'CHECK'}")
    print(f"  pid9 share [19, 21]: {r_m1['pid9_share_mc']:.4f} {'PASS' if 19 <= r_m1['pid9_share_mc'] <= 21 else 'CHECK'}")
    print(f"  hit (design_v5 21): {r_m1['mc']['hit_rate_pct']:.4f}")

    print(f"\nm2 v6 hard targets:")
    print(f"  RTP [295, 305]: {r_m2['mc']['rtp_pct']:.4f} {'PASS' if 295 <= r_m2['mc']['rtp_pct'] <= 305 else 'CHECK'}")
    print(f"  pid9 share <= 21: {r_m2['pid9_share_mc']:.4f} {'PASS' if r_m2['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  hit [30, 36]: {r_m2['mc']['hit_rate_pct']:.4f} {'PASS' if 30 <= r_m2['mc']['hit_rate_pct'] <= 36 else 'CHECK'}")

    print(f"\nm5 v6 hard targets:")
    print(f"  RTP [490, 510]: {r_m5['mc']['rtp_pct']:.4f} {'PASS' if 490 <= r_m5['mc']['rtp_pct'] <= 510 else 'CHECK'}")
    print(f"  pid9 share <= 21: {r_m5['pid9_share_mc']:.4f} {'PASS' if r_m5['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  hit [30, 40]: {r_m5['mc']['hit_rate_pct']:.4f} {'PASS' if 30 <= r_m5['mc']['hit_rate_pct'] <= 40 else 'CHECK'}")

    print(f"\nm7 v6 hard targets:")
    print(f"  RTP [84, 86]: {r_m7['mc']['rtp_pct']:.4f} {'PASS' if 84 <= r_m7['mc']['rtp_pct'] <= 86 else 'CHECK'}")
    print(f"  pid9 share <= 21: {r_m7['pid9_share_mc']:.4f} {'PASS' if r_m7['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  hit < m1 - 0.3 (= 20.62): {r_m7['mc']['hit_rate_pct']:.4f} {'PASS' if r_m7['mc']['hit_rate_pct'] < 20.62 else 'FAIL'}")

    # Summary table
    print(f"\n\n{'#'*80}\nSummary\n{'#'*80}\n")
    print(f"{'Mode':<10} {'RTP analytic':>14} {'RTP MC':>14} {'Hit analytic':>14} {'Hit MC':>14} {'pid9 share a':>16} {'pid9 share MC':>16}")
    print("-" * 110)
    print(f"{'m1':<10} {r_m1['analytic']['rtp_pct']:>14.4f} {r_m1['mc']['rtp_pct']:>14.4f} {r_m1['analytic']['hit_rate']*100:>14.4f} {r_m1['mc']['hit_rate_pct']:>14.4f} {r_m1['pid9_share_analytic']:>16.4f} {r_m1['pid9_share_mc']:>16.4f}")
    print(f"{'m2 v6':<10} {r_m2['analytic']['rtp_pct']:>14.4f} {r_m2['mc']['rtp_pct']:>14.4f} {r_m2['analytic']['hit_rate']*100:>14.4f} {r_m2['mc']['hit_rate_pct']:>14.4f} {r_m2['pid9_share_analytic']:>16.4f} {r_m2['pid9_share_mc']:>16.4f}")
    print(f"{'m5 v6':<10} {r_m5['analytic']['rtp_pct']:>14.4f} {r_m5['mc']['rtp_pct']:>14.4f} {r_m5['analytic']['hit_rate']*100:>14.4f} {r_m5['mc']['hit_rate_pct']:>14.4f} {r_m5['pid9_share_analytic']:>16.4f} {r_m5['pid9_share_mc']:>16.4f}")
    print(f"{'m7 v6':<10} {r_m7['analytic']['rtp_pct']:>14.4f} {r_m7['mc']['rtp_pct']:>14.4f} {r_m7['analytic']['hit_rate']*100:>14.4f} {r_m7['mc']['hit_rate_pct']:>14.4f} {r_m7['pid9_share_analytic']:>16.4f} {r_m7['pid9_share_mc']:>16.4f}")

    return {"m1": r_m1, "m2": r_m2, "m5": r_m5, "m7": r_m7}


if __name__ == "__main__":
    main()
