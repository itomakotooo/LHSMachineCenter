"""Final tightening: 50 total seeds at 100k each = 5M spins.
Goal: SE of mean to ~0.4pp, definitively answer P(mean < 84)."""
from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from session_artifacts.M37.scripts.empirical_v9_subgate import (
    M7_V9_W, analytic_summary, monte_carlo, RTP_FLOOR,
)

a = analytic_summary(M7_V9_W)
profile = a["profile"]
engine = a["engine"]

analytic_rtp = profile["rtp_pct"]
analytic_cv = profile["cv"]

# Original 7 seeds and follow-up 14 seeds combined
prior_rtps = [
    80.5390, 86.2270, 82.5670, 83.5090, 82.3030, 79.7680, 82.6370,  # original 7
    82.8080, 86.6700, 88.2480, 87.5490, 82.8030, 86.5050, 84.4960,  # +14
    85.6190, 81.6850, 83.3160, 79.7160, 87.0520, 85.4410, 84.6490,
]
prior_hits = [
    16.9680, 16.8470, 17.0420, 16.8370, 17.0880, 17.3030, 16.7750,
    16.8660, 17.1070, 17.2230, 17.1270, 16.8810, 16.9680, 16.8460,
    16.9460, 16.9730, 17.2160, 17.0270, 16.9910, 17.0000, 17.1270,
]
prior_pid9 = [
    28.2733, 25.5709, 27.4553, 26.2247, 27.9637, 28.6594, 26.8621,
    27.3222, 26.2444, 25.4669, 26.1099, 27.5364, 25.3211, 26.0119,
    26.5560, 27.3416, 26.2819, 27.7071, 25.7984, 26.1116, 27.2395,
]

# 29 more seeds (primes/random) → 50 total
new_seeds = [67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137,
             139, 149, 151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211]

print(f"Running {len(new_seeds)} more seeds (50 total = 5M spins)...")
new_rtps = []
new_hits = []
new_pid9 = []
for seed in new_seeds:
    mc = monte_carlo(engine, 100_000, seed=seed)
    pid9_share = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0
    new_rtps.append(mc["rtp_pct"])
    new_hits.append(mc["hit_rate_pct"])
    new_pid9.append(pid9_share)

all_rtps = prior_rtps + new_rtps
all_hits = prior_hits + new_hits
all_pid9 = prior_pid9 + new_pid9
n_seeds = len(all_rtps)

rtp_mean = statistics.mean(all_rtps)
rtp_stdev = statistics.stdev(all_rtps)
rtp_se = rtp_stdev / math.sqrt(n_seeds)
rtp_ci95 = 1.96 * rtp_se

hit_mean = statistics.mean(all_hits)
hit_stdev = statistics.stdev(all_hits)
hit_se = hit_stdev / math.sqrt(n_seeds)
hit_ci95 = 1.96 * hit_se

pid9_mean = statistics.mean(all_pid9)
pid9_stdev = statistics.stdev(all_pid9)

rtp_below = sum(1 for r in all_rtps if r < RTP_FLOOR)

# Also rate of seeds with empirical hit > 17 (upper hit ceiling)
hit_above_17 = sum(1 for h in all_hits if h > 17.0)
hit_above_20_62 = sum(1 for h in all_hits if h > 20.62)

print(f"\n{'='*80}")
print(f"v9 m7 RTP/Hit stress final: {n_seeds} seeds x 100k = {n_seeds*100_000:,} total spins")
print(f"Analytic RTP: {analytic_rtp:.4f}, Hit: {profile['hit_rate']*100:.4f}, CV: {analytic_cv:.4f}")
print(f"{'='*80}")
print(f"\nRTP:")
print(f"  Mean: {rtp_mean:.4f} (analytic {analytic_rtp:.4f}; drift {rtp_mean - analytic_rtp:+.4f}pp = {(rtp_mean-analytic_rtp)/rtp_se:+.2f}sigma)")
print(f"  SE of mean: {rtp_se:.4f}")
print(f"  95% CI of mean: [{rtp_mean - rtp_ci95:.4f}, {rtp_mean + rtp_ci95:.4f}]")
print(f"  Stdev across seeds: {rtp_stdev:.4f}")
print(f"  Range: [{min(all_rtps):.4f}, {max(all_rtps):.4f}]")
print(f"  Margin to floor {RTP_FLOOR}: {rtp_mean - RTP_FLOOR:+.4f}pp")
print(f"  CI lower margin to floor: {rtp_mean - rtp_ci95 - RTP_FLOOR:+.4f}pp")
print(f"  Seeds below floor: {rtp_below}/{n_seeds} ({100*rtp_below/n_seeds:.1f}%)")

print(f"\nHit:")
print(f"  Mean: {hit_mean:.4f} (analytic {profile['hit_rate']*100:.4f}; drift {hit_mean - profile['hit_rate']*100:+.4f}pp)")
print(f"  SE of mean: {hit_se:.4f}, 95% CI: [{hit_mean - hit_ci95:.4f}, {hit_mean + hit_ci95:.4f}]")
print(f"  Stdev across seeds: {hit_stdev:.4f}, Range: [{min(all_hits):.4f}, {max(all_hits):.4f}]")
print(f"  Seeds with hit > 17: {hit_above_17}/{n_seeds} ({100*hit_above_17/n_seeds:.1f}%)")
print(f"  Seeds with hit > 20.62 (universal §9 ceiling): {hit_above_20_62}/{n_seeds}")

print(f"\npid 9 share mean: {pid9_mean:.4f} (analytic 26.7739, drift {pid9_mean - 26.7739:+.4f}pp)")

# Final verdict
print(f"\n{'='*80}")
mean_pass = rtp_mean >= RTP_FLOOR
ci_pass = rtp_mean - rtp_ci95 >= RTP_FLOOR
buffer_pass = rtp_mean >= RTP_FLOOR + 0.1

if mean_pass and buffer_pass and ci_pass:
    verdict = "PASS-COMFORTABLE"
elif mean_pass and buffer_pass:
    verdict = "PASS-WITH-BUFFER (mean above floor + 0.1pp; CI lower below floor)"
elif mean_pass:
    verdict = "PASS-MARGINAL (mean at floor; ~50% of seeds below)"
else:
    verdict = "FAIL"

print(f"VERDICT: {verdict}")
print(f"  Mean RTP: {rtp_mean:.4f}")
print(f"  Margin to floor: {rtp_mean - RTP_FLOOR:+.4f}pp")
print(f"  Hit mean: {hit_mean:.4f} (band [14, 17] upper limit)")
print(f"{'='*80}")
