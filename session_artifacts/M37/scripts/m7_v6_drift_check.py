"""Multi-seed MC for m7 v6 to confirm RTP convergence to analytic ~85.02."""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from session_artifacts.M37.scripts.empirical_v6_subgate import (
    M7_V6_W, M2_V6_W, analytic_summary, monte_carlo,
)

print("=" * 80)
print("m7 v6 multi-seed drift check (analytic RTP 85.021)")
print("=" * 80)

a = analytic_summary(M7_V6_W)
profile = a["profile"]
engine = a["engine"]
print(f"\nAnalytic m7 v6 RTP: {profile['rtp_pct']:.4f}")
print(f"Analytic m7 v6 hit: {profile['hit_rate']*100:.4f}")
print(f"Analytic m7 v6 pid9 share: {(profile['pay_rtp'].get('9',0)*100)/profile['rtp_pct']*100:.4f}")

rtps_m7, hits_m7, pid9s_m7 = [], [], []
for seed in [42, 12345, 7, 9999, 31415, 27182, 16180]:
    mc = monte_carlo(engine, 100_000, seed=seed)
    pid9_share = (mc['pay_rtp'].get('9',0)*100) / mc['rtp_pct'] * 100 if mc['rtp_pct'] > 0 else 0
    rtps_m7.append(mc['rtp_pct'])
    hits_m7.append(mc['hit_rate_pct'])
    pid9s_m7.append(pid9_share)
    print(f"  seed={seed}: RTP={mc['rtp_pct']:.4f} (+/-{mc['rtp_ci_95_pp']:.4f}pp 95%) hit={mc['hit_rate_pct']:.4f} pid9_share={pid9_share:.4f}")

print(f"\nAcross {len(rtps_m7)} seeds @100k (= {100_000*len(rtps_m7):,} spins total):")
print(f"  RTP mean={statistics.mean(rtps_m7):.4f}, stdev={statistics.stdev(rtps_m7):.4f}")
print(f"  hit mean={statistics.mean(hits_m7):.4f}, stdev={statistics.stdev(hits_m7):.4f}")
print(f"  pid9_share mean={statistics.mean(pid9s_m7):.4f}, stdev={statistics.stdev(pid9s_m7):.4f}")

# Also m2 quick multi-seed
print(f"\n{'=' * 80}\nm2 v6 multi-seed drift check (analytic RTP 303.452)\n{'=' * 80}")
a2 = analytic_summary(M2_V6_W)
prof2 = a2["profile"]
eng2 = a2["engine"]

rtps_m2 = []
hits_m2 = []
pid9s_m2 = []
for seed in [42, 12345, 7, 9999, 31415, 27182, 16180]:
    mc = monte_carlo(eng2, 100_000, seed=seed)
    pid9_share = (mc['pay_rtp'].get('9',0)*100) / mc['rtp_pct'] * 100 if mc['rtp_pct'] > 0 else 0
    rtps_m2.append(mc['rtp_pct'])
    hits_m2.append(mc['hit_rate_pct'])
    pid9s_m2.append(pid9_share)
    print(f"  seed={seed}: RTP={mc['rtp_pct']:.4f} hit={mc['hit_rate_pct']:.4f} pid9_share={pid9_share:.4f}")

print(f"\nAcross {len(rtps_m2)} seeds @100k (= {100_000*len(rtps_m2):,} spins total):")
print(f"  RTP mean={statistics.mean(rtps_m2):.4f}, stdev={statistics.stdev(rtps_m2):.4f}")
print(f"  hit mean={statistics.mean(hits_m2):.4f}, stdev={statistics.stdev(hits_m2):.4f}")
print(f"  pid9_share mean={statistics.mean(pid9s_m2):.4f}, stdev={statistics.stdev(pid9s_m2):.4f}")
