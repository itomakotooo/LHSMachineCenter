"""Follow-up: expand sample to disambiguate RTP drift on v9 m7.

The 7x100k mean was 82.51 vs analytic 84.01. Two possible explanations:
1. Sampling tail (variance is genuinely 2.83pp single-seed SE at 100k)
2. Systematic bias (engine/analytic divergence)

Run additional seeds + larger per-seed samples to bound the mean tighter.
"""
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

print(f"=" * 80)
print(f"v9 m7 RTP stress follow-up")
print(f"Analytic RTP: {analytic_rtp:.4f}, CV: {analytic_cv:.4f}")
print(f"Floor: {RTP_FLOOR}")
print(f"=" * 80)

# Run 20 additional seeds at 100k each (total = 27 seeds x 100k = 2.7M new spins)
# Combined with the original 7 seeds = aggregate dataset for CI tightening
print(f"\n14 additional seeds at 100k each:")
seeds = [11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61]
new_rtps = []
new_hits = []
new_pid9 = []
for seed in seeds:
    mc = monte_carlo(engine, 100_000, seed=seed)
    pid9_share = (mc["pay_rtp"].get("9", 0) * 100) / mc["rtp_pct"] * 100 if mc["rtp_pct"] > 0 else 0
    new_rtps.append(mc["rtp_pct"])
    new_hits.append(mc["hit_rate_pct"])
    new_pid9.append(pid9_share)
    flag = "below" if mc["rtp_pct"] < RTP_FLOOR else "above"
    print(f"  seed={seed:5d}: RTP={mc['rtp_pct']:.4f} ({flag} floor); hit={mc['hit_rate_pct']:.4f}; pid9={pid9_share:.4f}%")

# Combine with original 7 seeds
original_rtps = [80.5390, 86.2270, 82.5670, 83.5090, 82.3030, 79.7680, 82.6370]
original_hits = [16.9680, 16.8470, 17.0420, 16.8370, 17.0880, 17.3030, 16.7750]
original_pid9 = [28.2733, 25.5709, 27.4553, 26.2247, 27.9637, 28.6594, 26.8621]

all_rtps = original_rtps + new_rtps
all_hits = original_hits + new_hits
all_pid9 = original_pid9 + new_pid9
n_seeds = len(all_rtps)

rtp_mean = statistics.mean(all_rtps)
rtp_stdev = statistics.stdev(all_rtps)
rtp_min = min(all_rtps)
rtp_max = max(all_rtps)
rtp_se_mean = rtp_stdev / math.sqrt(n_seeds)
rtp_ci95 = 1.96 * rtp_se_mean
rtp_below = sum(1 for r in all_rtps if r < RTP_FLOOR)

hit_mean = statistics.mean(all_hits)
hit_stdev = statistics.stdev(all_hits)
pid9_mean = statistics.mean(all_pid9)
pid9_stdev = statistics.stdev(all_pid9)

print(f"\n=" * 1)
print(f"Combined {n_seeds} seeds x 100k = {n_seeds * 100_000:,} total spins")
print(f"=" * 80)
print(f"RTP mean: {rtp_mean:.4f} (analytic {analytic_rtp:.4f}; drift {rtp_mean - analytic_rtp:+.4f}pp)")
print(f"RTP SE of mean: {rtp_se_mean:.4f}, 95% CI: [{rtp_mean - rtp_ci95:.4f}, {rtp_mean + rtp_ci95:.4f}]")
print(f"RTP stdev across seeds: {rtp_stdev:.4f}")
print(f"RTP range: [{rtp_min:.4f}, {rtp_max:.4f}]")
print(f"Seeds below {RTP_FLOOR}: {rtp_below}/{n_seeds} ({100*rtp_below/n_seeds:.1f}%)")
print(f"Hit mean: {hit_mean:.4f} (stdev {hit_stdev:.4f})")
print(f"pid 9 share mean: {pid9_mean:.4f} (stdev {pid9_stdev:.4f})")

# Drift sigma using observed seed stdev
drift = rtp_mean - analytic_rtp
drift_sigma = drift / rtp_se_mean if rtp_se_mean > 0 else 0
print(f"\nDrift sigma (vs analytic, using observed seed-mean SE): {drift_sigma:+.4f}sigma")

# Expected SE under analytic CV
expected_se_single_seed = analytic_cv * (analytic_rtp / 100) / math.sqrt(100_000) * 100
expected_se_mean_combined = expected_se_single_seed / math.sqrt(n_seeds)
print(f"Expected SE under analytic CV ({analytic_cv:.4f}): single-seed +/-{expected_se_single_seed:.4f}pp, combined +/-{expected_se_mean_combined:.4f}pp")
drift_sigma_analytic = drift / expected_se_mean_combined if expected_se_mean_combined > 0 else 0
print(f"Drift sigma (using analytic CV expected SE): {drift_sigma_analytic:+.4f}sigma")

# PASS / FAIL
print(f"\n{'='*80}")
if rtp_mean >= RTP_FLOOR and rtp_mean - rtp_ci95 >= RTP_FLOOR:
    print(f"VERDICT: PASS COMFORTABLE")
elif rtp_mean >= RTP_FLOOR:
    print(f"VERDICT: PASS NARROW (mean >= floor but CI lower < floor)")
else:
    print(f"VERDICT: FAIL")
print(f"  Mean RTP: {rtp_mean:.4f} vs floor {RTP_FLOOR}: margin {rtp_mean - RTP_FLOOR:+.4f}pp")
print(f"  CI lower: {rtp_mean - rtp_ci95:.4f} vs floor {RTP_FLOOR}: margin {rtp_mean - rtp_ci95 - RTP_FLOOR:+.4f}pp")
