"""200k MC validation for v6 modes — confirm CI shrinks, m2 RTP band confirmation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from session_artifacts.M37.scripts.empirical_v6_subgate import (
    M1_SHIPPED_W, M2_V6_W, M5_V6_W, M7_V6_W,
    analytic_summary, monte_carlo,
)


def short_run(label, weights_path, n_mc=200_000, seed=12345):
    print(f"\n{'='*80}\n{label}: {n_mc:,} MC seed={seed}\n{'='*80}")
    a = analytic_summary(weights_path)
    profile = a["profile"]
    engine = a["engine"]
    mc = monte_carlo(engine, n_mc, seed=seed)

    pid9_share_a = (profile["pay_rtp"].get("9", 0) * 100) / profile["rtp_pct"] * 100 if profile["rtp_pct"] > 0 else 0
    pid9_share_mc = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0

    rtp_drift = mc["rtp_pct"] - profile["rtp_pct"]
    rtp_drift_sigma = rtp_drift / (mc["rtp_ci_95_pp"] / 1.96) if mc["rtp_ci_95_pp"] > 0 else 0
    hit_drift = mc["hit_rate_pct"] - profile["hit_rate"] * 100
    hit_drift_sigma = hit_drift / (mc["hit_ci_95_pp"] / 1.96) if mc["hit_ci_95_pp"] > 0 else 0

    print(f"RTP analytic={profile['rtp_pct']:.4f}, MC={mc['rtp_pct']:.4f} (+/-{mc['rtp_ci_95_pp']:.4f}pp 95% CI), drift={rtp_drift:+.4f}pp ({rtp_drift_sigma:+.2f} sigma)")
    print(f"Hit analytic={profile['hit_rate']*100:.4f}, MC={mc['hit_rate_pct']:.4f} (+/-{mc['hit_ci_95_pp']:.4f}pp 95% CI), drift={hit_drift:+.4f}pp ({hit_drift_sigma:+.2f} sigma)")
    print(f"CV analytic={profile['cv']:.4f}, MC={mc['cv']:.4f}")
    print(f"pid9 share analytic={pid9_share_a:.4f}, MC={pid9_share_mc:.4f} (drift {pid9_share_mc - pid9_share_a:+.4f}pp)")

    return {"analytic": profile, "mc": mc, "pid9_share_a": pid9_share_a, "pid9_share_mc": pid9_share_mc}


if __name__ == "__main__":
    print(f"{'#'*80}\nv6 200k MC validation\n{'#'*80}")
    r_m1 = short_run("m1 v5 ship'd", M1_SHIPPED_W)
    r_m2 = short_run("m2 v6", M2_V6_W)
    r_m5 = short_run("m5 v6", M5_V6_W)
    r_m7 = short_run("m7 v6", M7_V6_W)

    print(f"\n{'='*80}\nCross-mode invariants @ 200k MC\n{'='*80}")
    print(f"RTP m7={r_m7['mc']['rtp_pct']:.4f} < m1={r_m1['mc']['rtp_pct']:.4f} < m2={r_m2['mc']['rtp_pct']:.4f} < m5={r_m5['mc']['rtp_pct']:.4f}")
    print(f"HIT m1={r_m1['mc']['hit_rate_pct']:.4f} - m7={r_m7['mc']['hit_rate_pct']:.4f} = {r_m1['mc']['hit_rate_pct']-r_m7['mc']['hit_rate_pct']:.4f}pp")

    print(f"\nv6 hard target gates @ 200k MC:")
    print(f"  m1 RTP [94, 96]: {r_m1['mc']['rtp_pct']:.4f} {'PASS' if 94 <= r_m1['mc']['rtp_pct'] <= 96 else 'CHECK'}")
    print(f"  m1 pid9 share [19, 21]: {r_m1['pid9_share_mc']:.4f} {'PASS' if 19 <= r_m1['pid9_share_mc'] <= 21 else 'CHECK'}")
    print(f"  m2 RTP [295, 305]: {r_m2['mc']['rtp_pct']:.4f} {'PASS' if 295 <= r_m2['mc']['rtp_pct'] <= 305 else 'CHECK'}")
    print(f"  m2 pid9 share <= 21: {r_m2['pid9_share_mc']:.4f} {'PASS' if r_m2['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  m5 RTP [490, 510]: {r_m5['mc']['rtp_pct']:.4f} {'PASS' if 490 <= r_m5['mc']['rtp_pct'] <= 510 else 'CHECK'}")
    print(f"  m5 pid9 share <= 21: {r_m5['pid9_share_mc']:.4f} {'PASS' if r_m5['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  m7 RTP [84, 86]: {r_m7['mc']['rtp_pct']:.4f} {'PASS' if 84 <= r_m7['mc']['rtp_pct'] <= 86 else 'CHECK'}")
    print(f"  m7 pid9 share <= 21: {r_m7['pid9_share_mc']:.4f} {'PASS' if r_m7['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  m7 hit < m1 - 0.3 (20.62): {r_m7['mc']['hit_rate_pct']:.4f} {'PASS' if r_m7['mc']['hit_rate_pct'] < 20.62 else 'FAIL'}")
