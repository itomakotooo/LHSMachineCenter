"""200k spin Monte Carlo for tighter CI on v5 m1 + m7."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from session_artifacts.M37.scripts.empirical_v5_subgate import (
    M1_V5_W, M7_V5_W, M2_BASE_W, M5_BASE_W, analytic_summary, monte_carlo,
)


def short_run(label, weights_path, n_mc=200_000):
    print(f"\n{'='*80}\n{label}: 200k MC\n{'='*80}")
    a = analytic_summary(weights_path)
    profile = a["profile"]
    engine = a["engine"]
    mc = monte_carlo(engine, n_mc, seed=12345)

    pid9_share_a = (profile["pay_rtp"].get("9", 0) * 100) / profile["rtp_pct"] * 100 if profile["rtp_pct"] > 0 else 0
    pid9_share_mc = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0

    print(f"RTP analytic={profile['rtp_pct']:.4f}, MC={mc['rtp_pct']:.4f} (±{mc['rtp_ci_95_pp']:.4f}pp 95% CI)")
    print(f"Hit analytic={profile['hit_rate']*100:.4f}, MC={mc['hit_rate_pct']:.4f} (±{mc['hit_ci_95_pp']:.4f}pp 95% CI)")
    print(f"CV analytic={profile['cv']:.4f}, MC={mc['cv']:.4f}")
    print(f"pid9 share analytic={pid9_share_a:.4f}, MC={pid9_share_mc:.4f}")

    # pid9 share 95% CI by delta method (RTP9/RTP_total → propagate variances)
    # Simpler: compute pid9 share for batches
    # Quick: 1.96 * sqrt(p*(1-p)/n) on pid9_rtp/(rtp_total*n*0.01) — but ratio of two means is harder.
    # Use a bootstrap proxy: 95% CI of RTP_total is known; effect on pid9 share is bounded.
    return {"analytic": profile, "mc": mc, "pid9_share_a": pid9_share_a, "pid9_share_mc": pid9_share_mc}


if __name__ == "__main__":
    r_m1 = short_run("v5 m1", M1_V5_W)
    r_m7 = short_run("v5 m7", M7_V5_W)
    r_m2 = short_run("baseline m2", M2_BASE_W)
    r_m5 = short_run("baseline m5", M5_BASE_W)

    print(f"\n{'='*80}\nCross-mode invariants @ 200k MC\n{'='*80}")
    print(f"RTP m7={r_m7['mc']['rtp_pct']:.4f} < m1={r_m1['mc']['rtp_pct']:.4f} < m2={r_m2['mc']['rtp_pct']:.4f} < m5={r_m5['mc']['rtp_pct']:.4f}")
    print(f"HIT m1={r_m1['mc']['hit_rate_pct']:.4f} - m7={r_m7['mc']['hit_rate_pct']:.4f} = {r_m1['mc']['hit_rate_pct']-r_m7['mc']['hit_rate_pct']:.4f}pp")
    print(f"1000× freq m1={r_m1['mc']['bucket_rate'].get('ge1000_lt5000',0)*100:.6f}%, m2={r_m2['mc']['bucket_rate'].get('ge1000_lt5000',0)*100:.6f}%, m5={r_m5['mc']['bucket_rate'].get('ge1000_lt5000',0)*100:.6f}%")

    print(f"\nv5 m1 hard target gates @ 200k:")
    print(f"  pid9 share [19, 21]: {r_m1['pid9_share_mc']:.4f} {'PASS' if 19 <= r_m1['pid9_share_mc'] <= 21 else 'FAIL'}")
    print(f"  pid9 share empirical band [18.5, 21.5]: {'PASS' if 18.5 <= r_m1['pid9_share_mc'] <= 21.5 else 'FAIL'}")
    print(f"  RTP [94, 96]: {r_m1['mc']['rtp_pct']:.4f} {'PASS' if 94 <= r_m1['mc']['rtp_pct'] <= 96 else 'FAIL'}")
