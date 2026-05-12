"""Multi-seed MC for m7 to check drift."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from session_artifacts.M37.scripts.empirical_v5_subgate import (
    M7_V5_W, analytic_summary, monte_carlo,
)

a = analytic_summary(M7_V5_W)
profile = a["profile"]
engine = a["engine"]
print(f"Analytic m7 RTP: {profile['rtp_pct']:.4f}")
print(f"Analytic m7 hit: {profile['hit_rate']*100:.4f}")
print(f"Analytic m7 pid9 share: {(profile['pay_rtp'].get('9',0)*100)/profile['rtp_pct']*100:.4f}")
print()

rtps = []
hits = []
pid9s = []
for seed in [42, 12345, 7, 9999, 31415, 27182]:
    mc = monte_carlo(engine, 100_000, seed=seed)
    pid9_share = (mc['pay_rtp'].get('9',0)*100) / mc['rtp_pct'] * 100 if mc['rtp_pct'] > 0 else 0
    rtps.append(mc['rtp_pct'])
    hits.append(mc['hit_rate_pct'])
    pid9s.append(pid9_share)
    print(f"seed={seed}: RTP={mc['rtp_pct']:.4f} (±{mc['rtp_ci_95_pp']:.4f}pp 95%) hit={mc['hit_rate_pct']:.4f} pid9_share={pid9_share:.4f}")

import statistics
print(f"\nAcross {len(rtps)} seeds @100k:")
print(f"  RTP mean={statistics.mean(rtps):.4f}, stdev={statistics.stdev(rtps):.4f}")
print(f"  hit mean={statistics.mean(hits):.4f}, stdev={statistics.stdev(hits):.4f}")
print(f"  pid9_share mean={statistics.mean(pid9s):.4f}, stdev={statistics.stdev(pid9s):.4f}")
