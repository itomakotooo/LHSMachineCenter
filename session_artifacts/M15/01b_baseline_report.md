# M15 — Stage 1b Comprehensive Baseline Report

> **Agent**: Analyst (A) per [`slot_designer/ONBOARDING_PROCESS.md`](../../slot_designer/ONBOARDING_PROCESS.md) §4 / §5.1b 12-section spec.
>
> **Generated**: 2026-05-11T00:26:28Z
>
> **Script**: [`scripts/baseline_dump.py`](scripts/baseline_dump.py)
>
> **Inputs**:
> - `slot_designer\machines\M15\spec.json` (paytable mechanism — `_design`/`_notes`/`_weights_rationale` IGNORED per process_improvements.md #2)
> - `slot_designer\machines\M15\reel_strips.json` (reel strip layout — 36 stops × 3 reels)
> - `slot_designer\machines\M15\weights/mode_{1,2,5,7}/weights.json` (per-mode v7 weights — `_tuned_summary` IGNORED)
> - `rawdata\M15$TopDollarSelector$0$/mode_{1,2,5,7}/` (production rawdata for §12 schema fingerprint)

**Universal § references in this report**: ONBOARDING_PROCESS.md §5.1b (12-section spec) · DESIGN_PHILOSOPHY.md §7 (top-jackpot escalation), §9 (mode-pair monotonicity), §12 (reel asymmetry), §13 (blank-flank diversity), §15 (PWDF window visibility).

**Reading order**: §1 / §11 first (totals + cross-mode invariants), then §3 / §4 (per-pay_id / family), then §6 / §7 / §8 (strip-level structure), then §9 / §10 (feature + escalation), §12 (schema sanity).

---

## §1 Per-mode totals — RTP / hit / std / CV / split / trigger / feature EV

> **Source**: `analytic_profile()` (base game) + `analyze_feature()` (feature plugin) per mode. Trigger rate derived from R3 topdollar marginal (see process_improvements.md #5 — scatter_trigger pay_id 666 with multiplier=0 doesn't fire in pay_hits).

| metric | mode 1 | mode 2 | mode 5 | mode 7 |
|---|---:|---:|---:|---:|
| Total RTP (%) | 94.983% | 294.282% | 490.324% | 85.090% |
| Base RTP (pp) | 43.152 | 132.762 | 132.762 | 33.238 |
| Feature RTP (pp) | 51.831 | 161.520 | 357.562 | 51.852 |
| Base : Feature split | 45.4 : 54.6 | 45.1 : 54.9 | 27.1 : 72.9 | 39.1 : 60.9 |
| Base hit rate | 19.312% | 29.353% | 29.353% | 14.920% |
| Base std_return_x | 2.4878 | 6.8224 | 6.8224 | 2.3491 |
| Base CV | 5.765 | 5.139 | 5.139 | 7.067 |
| Trigger rate | 1.127% (1 in 89) | 2.692% (1 in 37) | 2.692% (1 in 37) | 1.127% (1 in 89) |
| Feature EV (×bet) | 46.00× | 59.99× | 132.81× | 46.00× |
| Feature CV (conditional) | 0.735 | 0.778 | 0.858 | 0.735 |
| Feature R range | [5×, ...] | [5×, ...] | [5×, ...] | [5×, ...] |
|   (max) | [..., 4880×] | [..., 4880×] | [..., 4880×] | [..., 4880×] |
| One-round P(accept) | 23.52% | 35.41% | 67.66% | 23.52% |
| Total prob sanity (≈1) | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

**Reads** vs v7 quickref (`session_artifacts/M15/v7_baseline_quickref.md`): mode 1 hit 19.31%, base CV 5.77, feature CV 0.74, trigger 1/89, feature EV 46× — all match within sanity tolerance.

## §2 Bucket distribution — 11 buckets, rate% + RTP pp per mode

> **Source**: `analytic_profile()['bucket_rate']` + `['bucket_rtp']`. Buckets are analyzer's `return_bucket()` thresholds.

| bucket | m1 rate% | m1 RTP pp | m2 rate% | m2 RTP pp | m5 rate% | m5 RTP pp | m7 rate% | m7 RTP pp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ge5000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 |
| ge1000_lt5000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 |
| ge500_lt1000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 |
| ge200_lt500 | 0.0017% | 0.333 | 0.0135% | 2.702 | 0.0135% | 2.702 | 0.0018% | 0.357 |
| ge100_lt200 | 0.0062% | 0.739 | 0.0901% | 10.809 | 0.0901% | 10.809 | 0.0066% | 0.793 |
| ge50_lt100 | 0.0246% | 1.818 | 0.3156% | 21.493 | 0.3156% | 21.493 | 0.0234% | 1.707 |
| ge20_lt50 | 0.3491% | 8.671 | 1.5631% | 42.541 | 1.5631% | 42.541 | 0.2768% | 6.947 |
| ge10_lt20 | 0.4627% | 4.684 | 0.9531% | 9.622 | 0.9531% | 9.622 | 0.3248% | 3.276 |
| ge5_lt10 | 0.8345% | 4.172 | 1.1330% | 5.665 | 1.1330% | 5.665 | 0.5347% | 2.673 |
| ge1_lt5 | 17.6335% | 22.734 | 25.2849% | 39.929 | 25.2849% | 39.929 | 13.7519% | 17.485 |
| gt0_lt1 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 | 0.0000% | 0.000 |

**Players FEEL the bucket that has the most RTP weight** (Lucas & Singh 2008). The dominant base bucket is `ge1_lt5` (cherry-1 1× anywhere — archetype-mandated, see user_brief.md default decisions).

## §3 Per pay_id breakdown — probability + 1-in-N + RTP pp

> **Source**: `analytic_profile()['pay_hits']` + `['pay_rtp']`. Sorted by mode 1 RTP contribution (DESCENDING).

### mode 1

| pay_id | family | P(hit) | 1 in N | RTP pp |
|---|---|---:|---:|---:|
| 9 | cherry1 | 13.7705% | 7 | 13.771 |
| 8 | bar_mixed | 3.8629% | 26 | 8.964 |
| 5 | bar2 | 0.5805% | 172 | 8.780 |
| 3 | bar3 | 0.1087% | 920 | 4.185 |
| 71 | cherry2 | 0.7090% | 141 | 3.545 |
| 7 | bar1 | 0.2508% | 399 | 2.126 |
| 2 | high7_wild | 0.0137% | 7,319 | 1.189 |
| 1 | wild_pure | 0.0017% | 60,141 | 0.333 |
| 4 | cherry3 | 0.0114% | 8,782 | 0.171 |
| 21 | high7_pure | 0.0030% | 33,411 | 0.090 |

### mode 2

| pay_id | family | P(hit) | 1 in N | RTP pp |
|---|---|---:|---:|---:|
| 3 | bar3 | 0.6393% | 156 | 26.974 |
| 5 | bar2 | 1.4401% | 69 | 25.938 |
| 8 | bar_mixed | 9.8334% | 10 | 24.478 |
| 2 | high7_wild | 0.2777% | 360 | 22.069 |
| 9 | cherry1 | 15.4516% | 6 | 15.452 |
| 7 | bar1 | 0.6223% | 161 | 6.462 |
| 71 | cherry2 | 0.9322% | 107 | 4.661 |
| 21 | high7_pure | 0.1251% | 799 | 3.753 |
| 1 | wild_pure | 0.0135% | 7,401 | 2.702 |
| 4 | cherry3 | 0.0182% | 5,485 | 0.273 |

### mode 5

| pay_id | family | P(hit) | 1 in N | RTP pp |
|---|---|---:|---:|---:|
| 3 | bar3 | 0.6393% | 156 | 26.974 |
| 5 | bar2 | 1.4401% | 69 | 25.938 |
| 8 | bar_mixed | 9.8334% | 10 | 24.478 |
| 2 | high7_wild | 0.2777% | 360 | 22.069 |
| 9 | cherry1 | 15.4516% | 6 | 15.452 |
| 7 | bar1 | 0.6223% | 161 | 6.462 |
| 71 | cherry2 | 0.9322% | 107 | 4.661 |
| 21 | high7_pure | 0.1251% | 799 | 3.753 |
| 1 | wild_pure | 0.0135% | 7,401 | 2.702 |
| 4 | cherry3 | 0.0182% | 5,485 | 0.273 |

### mode 7

| pay_id | family | P(hit) | 1 in N | RTP pp |
|---|---|---:|---:|---:|
| 9 | cherry1 | 10.9960% | 9 | 10.996 |
| 5 | bar2 | 0.4208% | 238 | 6.645 |
| 8 | bar_mixed | 2.7559% | 36 | 6.489 |
| 3 | bar3 | 0.0836% | 1,196 | 3.362 |
| 71 | cherry2 | 0.4434% | 226 | 2.217 |
| 7 | bar1 | 0.1948% | 513 | 1.715 |
| 2 | high7_wild | 0.0147% | 6,824 | 1.276 |
| 1 | wild_pure | 0.0018% | 56,070 | 0.357 |
| 21 | high7_pure | 0.0032% | 31,150 | 0.096 |
| 4 | cherry3 | 0.0057% | 17,407 | 0.086 |

## §4 Family RTP share — M15 family aggregation

> **Source**: §3 rows grouped by family per `FAMILY_MAP` (sourced from `spec.json` pays[] — see top of `baseline_dump.py`). Share% computed against **base** RTP (excludes feature).

### mode 1  (base RTP = 43.152pp)

| family | P(hit) | RTP pp | share of base | share of total |
|---|---:|---:|---:|---:|
| cherry1 | 13.7705% | 13.771 | 31.91% | 14.50% |
| bar_mixed | 3.8629% | 8.964 | 20.77% | 9.44% |
| bar2 | 0.5805% | 8.780 | 20.35% | 9.24% |
| bar3 | 0.1087% | 4.185 | 9.70% | 4.41% |
| cherry2 | 0.7090% | 3.545 | 8.22% | 3.73% |
| bar1 | 0.2508% | 2.126 | 4.93% | 2.24% |
| high7_wild | 0.0137% | 1.189 | 2.76% | 1.25% |
| wild_pure | 0.0017% | 0.333 | 0.77% | 0.35% |
| cherry3 | 0.0114% | 0.171 | 0.40% | 0.18% |
| high7_pure | 0.0030% | 0.090 | 0.21% | 0.09% |

### mode 2  (base RTP = 132.762pp)

| family | P(hit) | RTP pp | share of base | share of total |
|---|---:|---:|---:|---:|
| bar3 | 0.6393% | 26.974 | 20.32% | 9.17% |
| bar2 | 1.4401% | 25.938 | 19.54% | 8.81% |
| bar_mixed | 9.8334% | 24.478 | 18.44% | 8.32% |
| high7_wild | 0.2777% | 22.069 | 16.62% | 7.50% |
| cherry1 | 15.4516% | 15.452 | 11.64% | 5.25% |
| bar1 | 0.6223% | 6.462 | 4.87% | 2.20% |
| cherry2 | 0.9322% | 4.661 | 3.51% | 1.58% |
| high7_pure | 0.1251% | 3.753 | 2.83% | 1.28% |
| wild_pure | 0.0135% | 2.702 | 2.04% | 0.92% |
| cherry3 | 0.0182% | 0.273 | 0.21% | 0.09% |

### mode 5  (base RTP = 132.762pp)

| family | P(hit) | RTP pp | share of base | share of total |
|---|---:|---:|---:|---:|
| bar3 | 0.6393% | 26.974 | 20.32% | 5.50% |
| bar2 | 1.4401% | 25.938 | 19.54% | 5.29% |
| bar_mixed | 9.8334% | 24.478 | 18.44% | 4.99% |
| high7_wild | 0.2777% | 22.069 | 16.62% | 4.50% |
| cherry1 | 15.4516% | 15.452 | 11.64% | 3.15% |
| bar1 | 0.6223% | 6.462 | 4.87% | 1.32% |
| cherry2 | 0.9322% | 4.661 | 3.51% | 0.95% |
| high7_pure | 0.1251% | 3.753 | 2.83% | 0.77% |
| wild_pure | 0.0135% | 2.702 | 2.04% | 0.55% |
| cherry3 | 0.0182% | 0.273 | 0.21% | 0.06% |

### mode 7  (base RTP = 33.238pp)

| family | P(hit) | RTP pp | share of base | share of total |
|---|---:|---:|---:|---:|
| cherry1 | 10.9960% | 10.996 | 33.08% | 12.92% |
| bar2 | 0.4208% | 6.645 | 19.99% | 7.81% |
| bar_mixed | 2.7559% | 6.489 | 19.52% | 7.63% |
| bar3 | 0.0836% | 3.362 | 10.12% | 3.95% |
| cherry2 | 0.4434% | 2.217 | 6.67% | 2.61% |
| bar1 | 0.1948% | 1.715 | 5.16% | 2.02% |
| high7_wild | 0.0147% | 1.276 | 3.84% | 1.50% |
| wild_pure | 0.0018% | 0.357 | 1.07% | 0.42% |
| high7_pure | 0.0032% | 0.096 | 0.29% | 0.11% |
| cherry3 | 0.0057% | 0.086 | 0.26% | 0.10% |

## §5 Per-reel symbol marginals (mid-row payline)

> **Source**: `compute_reel_marginal(reel)` per reel. Probability that the mid-row symbol on each reel == named symbol. Constraint: each reel column sums to 1.0.

### mode 1

| symbol | R1 | R2 | R3 |
|---|---:|---:|---:|
| 1bar | 10.597% | 9.499% | 12.465% |
| 2bar | 14.802% | 14.248% | 16.620% |
| 3bar | 7.738% | 6.332% | 8.662% |
| blank | 54.500% | 54.617% | 54.507% |
| cherry | 6.056% | 6.069% | 3.099% |
| doublediamond | 3.196% | 3.694% | 1.408% |
| high7 | 3.028% | 5.013% | 1.972% |
| jackpot | 0.084% | 0.528% | 0.141% |
| topdollar | 0.000% | 0.000% | 1.127% |

### mode 2

| symbol | R1 | R2 | R3 |
|---|---:|---:|---:|
| 1bar | 11.033% | 10.698% | 17.019% |
| 2bar | 17.513% | 16.048% | 22.692% |
| 3bar | 16.112% | 7.132% | 16.154% |
| blank | 34.676% | 34.770% | 24.231% |
| cherry | 6.305% | 6.835% | 4.231% |
| doublediamond | 5.254% | 8.915% | 2.885% |
| high7 | 8.757% | 14.859% | 9.615% |
| jackpot | 0.350% | 0.743% | 0.481% |
| topdollar | 0.000% | 0.000% | 2.692% |

### mode 5

| symbol | R1 | R2 | R3 |
|---|---:|---:|---:|
| 1bar | 11.033% | 10.698% | 17.019% |
| 2bar | 17.513% | 16.048% | 22.692% |
| 3bar | 16.112% | 7.132% | 16.154% |
| blank | 34.676% | 34.770% | 24.231% |
| cherry | 6.305% | 6.835% | 4.231% |
| doublediamond | 5.254% | 8.915% | 2.885% |
| high7 | 8.757% | 14.859% | 9.615% |
| jackpot | 0.350% | 0.743% | 0.481% |
| topdollar | 0.000% | 0.000% | 2.692% |

### mode 7

| symbol | R1 | R2 | R3 |
|---|---:|---:|---:|
| 1bar | 9.451% | 8.505% | 11.353% |
| 2bar | 13.247% | 11.856% | 15.137% |
| 3bar | 6.785% | 5.670% | 7.729% |
| blank | 59.612% | 60.309% | 57.971% |
| cherry | 4.523% | 4.639% | 2.738% |
| doublediamond | 3.069% | 3.608% | 1.610% |
| high7 | 2.908% | 4.897% | 2.254% |
| jackpot | 0.404% | 0.515% | 0.081% |
| topdollar | 0.000% | 0.000% | 1.127% |

## §6 Reel asymmetry — DESIGN_PHILOSOPHY §12

> **Source**: §5 marginals. M15 is **3-reel + R3 trigger reel** (topdollar only on R3 → §12.1 role (b)). Compare non-trigger top-prize density between R1 (winners-friendly) and R3.
>
> **Universal direction lock (§12.2 3-reel)**:
> - R1 blank ≤ R3 blank
> - R1 top-prize density ≥ R3 top-prize density (excl. trigger)

| metric | mode 1 | mode 2 | mode 5 | mode 7 |
|---|---:|---:|---:|---:|
| R1 blank | 54.50% | 34.68% | 34.68% | 59.61% |
| R2 blank | 54.62% | 34.77% | 34.77% | 60.31% |
| R3 blank | 54.51% | 24.23% | 24.23% | 57.97% |
| Δ(R3-R1) blank pp | +0.01 | -10.45 | -10.45 | -1.64 |
| blank R1≤R3 direction ✓ | ✓ | ✗ | ✗ | ✗ |
| R1 top-prize density (excl. trigger) | 6.22% | 14.01% | 14.01% | 5.98% |
| R3 top-prize density (excl. trigger) | 3.38% | 12.50% | 12.50% | 3.86% |
| Δ(R1-R3) top-prize pp | +2.84 | +1.51 | +1.51 | +2.11 |
| top-prize R1≥R3 direction ✓ | ✓ | ✓ | ✓ | ✓ |

Per-symbol R1 vs R3 (mode 1):

| symbol | R1 | R2 | R3 |
|---|---:|---:|---:|
| doublediamond | 3.196% | 3.694% | 1.408% |
| high7 | 3.028% | 5.013% | 1.972% |

## §7 Window visibility (PWDF) — DESIGN_PHILOSOPHY §15

> **Source**: `player_experience.symbol_window_probability` / `symbol_mid_probability` / `pwdf_ratio`. **PWDF = p_window / p_mid**; >1 means symbol visually appears more than it pays (Harrigan 2009 clustering).
>
> M15 is a **3-reel physical** machine (no virtual reel mapping); §15.3 floor: 30-45% top-prize any-reel window visibility achievable. (Floor is machine-specific — written here as raw measurement; Designer decides target in Stage 4.)

### mode 1

| symbol | reel | p_mid | p_window | PWDF |
|---|---:|---:|---:|---:|
| doublediamond | R1 | 3.196% | 15.307% | 4.79 |
| doublediamond | R2 | 3.694% | 15.831% | 4.29 |
| doublediamond | R3 | 1.408% | 7.465% | 5.30 |
| **doublediamond (any-reel max)** | — | — | **15.83%** | — |
| high7 | R1 | 3.028% | 15.139% | 5.00 |
| high7 | R2 | 5.013% | 17.150% | 3.42 |
| high7 | R3 | 1.972% | 14.085% | 7.14 |
| **high7 (any-reel max)** | — | — | **17.15%** | — |
| 3bar | R1 | 7.738% | 31.960% | 4.13 |
| 3bar | R2 | 6.332% | 30.607% | 4.83 |
| 3bar | R3 | 8.662% | 26.831% | 3.10 |
| **3bar (any-reel max)** | — | — | **31.96%** | — |
| 2bar | R1 | 14.802% | 39.024% | 2.64 |
| 2bar | R2 | 14.248% | 38.522% | 2.70 |
| 2bar | R3 | 16.620% | 40.845% | 2.46 |
| **2bar (any-reel max)** | — | — | **40.85%** | — |
| 1bar | R1 | 10.597% | 28.764% | 2.71 |
| 1bar | R2 | 9.499% | 27.704% | 2.92 |
| 1bar | R3 | 12.465% | 30.634% | 2.46 |
| **1bar (any-reel max)** | — | — | **30.63%** | — |
| cherry | R1 | 6.056% | 18.167% | 3.00 |
| cherry | R2 | 6.069% | 18.206% | 3.00 |
| cherry | R3 | 3.099% | 15.211% | 4.91 |
| **cherry (any-reel max)** | — | — | **18.21%** | — |
| topdollar | R1 | 0.000% | 0.000% | 0.00 |
| topdollar | R2 | 0.000% | 0.000% | 0.00 |
| topdollar | R3 | 1.127% | 13.239% | 11.75 |
| **topdollar (any-reel max)** | — | — | **13.24%** | — |

### mode 2

| symbol | reel | p_mid | p_window | PWDF |
|---|---:|---:|---:|---:|
| doublediamond | R1 | 5.254% | 12.960% | 2.47 |
| doublediamond | R2 | 8.915% | 16.642% | 1.87 |
| doublediamond | R3 | 2.885% | 5.577% | 1.93 |
| **doublediamond (any-reel max)** | — | — | **16.64%** | — |
| high7 | R1 | 8.757% | 16.462% | 1.88 |
| high7 | R2 | 14.859% | 22.585% | 1.52 |
| high7 | R3 | 9.615% | 15.000% | 1.56 |
| **high7 (any-reel max)** | — | — | **22.59%** | — |
| 3bar | R1 | 16.112% | 31.524% | 1.96 |
| 3bar | R2 | 7.132% | 22.585% | 3.17 |
| 3bar | R3 | 16.154% | 24.231% | 1.50 |
| **3bar (any-reel max)** | — | — | **31.52%** | — |
| 2bar | R1 | 17.513% | 32.925% | 1.88 |
| 2bar | R2 | 16.048% | 31.501% | 1.96 |
| 2bar | R3 | 22.692% | 33.462% | 1.47 |
| **2bar (any-reel max)** | — | — | **33.46%** | — |
| 1bar | R1 | 11.033% | 22.592% | 2.05 |
| 1bar | R2 | 10.698% | 22.288% | 2.08 |
| 1bar | R3 | 17.019% | 25.096% | 1.47 |
| **1bar (any-reel max)** | — | — | **25.10%** | — |
| cherry | R1 | 6.305% | 14.011% | 2.22 |
| cherry | R2 | 6.835% | 14.562% | 2.13 |
| cherry | R3 | 4.231% | 9.615% | 2.27 |
| **cherry (any-reel max)** | — | — | **14.56%** | — |
| topdollar | R1 | 0.000% | 0.000% | 0.00 |
| topdollar | R2 | 0.000% | 0.000% | 0.00 |
| topdollar | R3 | 2.692% | 8.077% | 3.00 |
| **topdollar (any-reel max)** | — | — | **8.08%** | — |

### mode 5

| symbol | reel | p_mid | p_window | PWDF |
|---|---:|---:|---:|---:|
| doublediamond | R1 | 5.254% | 12.960% | 2.47 |
| doublediamond | R2 | 8.915% | 16.642% | 1.87 |
| doublediamond | R3 | 2.885% | 5.577% | 1.93 |
| **doublediamond (any-reel max)** | — | — | **16.64%** | — |
| high7 | R1 | 8.757% | 16.462% | 1.88 |
| high7 | R2 | 14.859% | 22.585% | 1.52 |
| high7 | R3 | 9.615% | 15.000% | 1.56 |
| **high7 (any-reel max)** | — | — | **22.59%** | — |
| 3bar | R1 | 16.112% | 31.524% | 1.96 |
| 3bar | R2 | 7.132% | 22.585% | 3.17 |
| 3bar | R3 | 16.154% | 24.231% | 1.50 |
| **3bar (any-reel max)** | — | — | **31.52%** | — |
| 2bar | R1 | 17.513% | 32.925% | 1.88 |
| 2bar | R2 | 16.048% | 31.501% | 1.96 |
| 2bar | R3 | 22.692% | 33.462% | 1.47 |
| **2bar (any-reel max)** | — | — | **33.46%** | — |
| 1bar | R1 | 11.033% | 22.592% | 2.05 |
| 1bar | R2 | 10.698% | 22.288% | 2.08 |
| 1bar | R3 | 17.019% | 25.096% | 1.47 |
| **1bar (any-reel max)** | — | — | **25.10%** | — |
| cherry | R1 | 6.305% | 14.011% | 2.22 |
| cherry | R2 | 6.835% | 14.562% | 2.13 |
| cherry | R3 | 4.231% | 9.615% | 2.27 |
| **cherry (any-reel max)** | — | — | **14.56%** | — |
| topdollar | R1 | 0.000% | 0.000% | 0.00 |
| topdollar | R2 | 0.000% | 0.000% | 0.00 |
| topdollar | R3 | 2.692% | 8.077% | 3.00 |
| **topdollar (any-reel max)** | — | — | **8.08%** | — |

### mode 7

| symbol | reel | p_mid | p_window | PWDF |
|---|---:|---:|---:|---:|
| doublediamond | R1 | 3.069% | 16.317% | 5.32 |
| doublediamond | R2 | 3.608% | 17.010% | 4.71 |
| doublediamond | R3 | 1.610% | 8.052% | 5.00 |
| **doublediamond (any-reel max)** | — | — | **17.01%** | — |
| high7 | R1 | 2.908% | 16.155% | 5.56 |
| high7 | R2 | 4.897% | 18.299% | 3.74 |
| high7 | R3 | 2.254% | 15.137% | 6.71 |
| **high7 (any-reel max)** | — | — | **18.30%** | — |
| 3bar | R1 | 6.785% | 33.279% | 4.90 |
| 3bar | R2 | 5.670% | 32.474% | 5.73 |
| 3bar | R3 | 7.729% | 27.053% | 3.50 |
| **3bar (any-reel max)** | — | — | **33.28%** | — |
| 2bar | R1 | 13.247% | 39.742% | 3.00 |
| 2bar | R2 | 11.856% | 38.660% | 3.26 |
| 2bar | R3 | 15.137% | 40.902% | 2.70 |
| **2bar (any-reel max)** | — | — | **40.90%** | — |
| 1bar | R1 | 9.451% | 29.321% | 3.10 |
| 1bar | R2 | 8.505% | 28.608% | 3.36 |
| 1bar | R3 | 11.353% | 30.676% | 2.70 |
| **1bar (any-reel max)** | — | — | **30.68%** | — |
| cherry | R1 | 4.523% | 17.771% | 3.93 |
| cherry | R2 | 4.639% | 18.041% | 3.89 |
| cherry | R3 | 2.738% | 15.620% | 5.71 |
| **cherry (any-reel max)** | — | — | **18.04%** | — |
| topdollar | R1 | 0.000% | 0.000% | 0.00 |
| topdollar | R2 | 0.000% | 0.000% | 0.00 |
| topdollar | R3 | 1.127% | 14.010% | 12.43 |
| **topdollar (any-reel max)** | — | — | **14.01%** | — |

## §8 Blank-flank diversity — DESIGN_PHILOSOPHY §13

> **Source**: direct reel strip scan. For each blank position i on each reel, check that `strip[i-1] != strip[i+1]` (cyclic). Universal hard rule: **0 violations**.
>
> NB: strip layout is byte-identical across modes (`reel_strips.json` is shared), so this section's result is mode-invariant. Reported once.

**Result**: 0 violations across 3 reels.

**Pass** ✓: True


## §9 Feature session bucket — per-trigger R distribution + cadence

> **Source**: 4-round accept/reroll math from `feature.analyze_feature` + bucketing into the same 11 buckets used in §2. Final R = bucketed expected payout per accepted session.
>
> Trigger cadence = 1 / R3 topdollar marginal (see process_improvements.md #5).

### mode 1

- **Trigger**: 1.127% per paid spin (1 in 89)
- **P(count_x = 1)** (single-card reveal): 5.00%
- **One-round P(R ≥ threshold)**: 23.52%
- **P(R ≥ 1000 | triggered)**: 0.00185%
- **P(R ≥ 1000 per paid spin)**: 0.000021% (1 in 4,809,365)

| bucket | P(this bucket \| triggered) | EV contribution |
|---|---:|---:|
| ge20_lt50 | 49.4985% | 16.527× |
| ge50_lt100 | 29.2000% | 18.421× |
| ge10_lt20 | 12.8286% | 1.512× |
| ge100_lt200 | 6.3091% | 7.577× |
| ge5_lt10 | 1.3747% | 0.069× |
| ge200_lt500 | 0.7814% | 1.838× |
| ge500_lt1000 | 0.0059% | 0.031× |
| ge1000_lt5000 | 0.0018% | 0.025× |

### mode 2

- **Trigger**: 2.692% per paid spin (1 in 37)
- **P(count_x = 1)** (single-card reveal): 5.00%
- **One-round P(R ≥ threshold)**: 35.41%
- **P(R ≥ 1000 | triggered)**: 0.01086%
- **P(R ≥ 1000 per paid spin)**: 0.000292% (1 in 341,923)

| bucket | P(this bucket \| triggered) | EV contribution |
|---|---:|---:|
| ge20_lt50 | 41.2364% | 14.818× |
| ge50_lt100 | 38.4408% | 24.793× |
| ge100_lt200 | 11.7781% | 14.447× |
| ge10_lt20 | 5.9389% | 0.719× |
| ge200_lt500 | 1.9555% | 4.863× |
| ge5_lt10 | 0.6123% | 0.031× |
| ge500_lt1000 | 0.0271% | 0.145× |
| ge1000_lt5000 | 0.0109% | 0.177× |

### mode 5

- **Trigger**: 2.692% per paid spin (1 in 37)
- **P(count_x = 1)** (single-card reveal): 5.00%
- **One-round P(R ≥ threshold)**: 67.66%
- **P(R ≥ 1000 | triggered)**: 0.00048%
- **P(R ≥ 1000 per paid spin)**: 0.000013% (1 in 7,808,346)

| bucket | P(this bucket \| triggered) | EV contribution |
|---|---:|---:|
| ge50_lt100 | 36.4357% | 23.838× |
| ge100_lt200 | 30.5238% | 38.872× |
| ge200_lt500 | 18.3119% | 53.008× |
| ge20_lt50 | 12.2593% | 4.855× |
| ge500_lt1000 | 2.1306% | 12.185× |
| ge10_lt20 | 0.3050% | 0.039× |
| ge5_lt10 | 0.0333% | 0.002× |
| ge1000_lt5000 | 0.0005% | 0.010× |

### mode 7

- **Trigger**: 1.127% per paid spin (1 in 89)
- **P(count_x = 1)** (single-card reveal): 5.00%
- **One-round P(R ≥ threshold)**: 23.52%
- **P(R ≥ 1000 | triggered)**: 0.00185%
- **P(R ≥ 1000 per paid spin)**: 0.000021% (1 in 4,807,429)

| bucket | P(this bucket \| triggered) | EV contribution |
|---|---:|---:|
| ge20_lt50 | 49.4985% | 16.527× |
| ge50_lt100 | 29.2000% | 18.421× |
| ge10_lt20 | 12.8286% | 1.512× |
| ge100_lt200 | 6.3091% | 7.577× |
| ge5_lt10 | 1.3747% | 0.069× |
| ge200_lt500 | 0.7814% | 1.838× |
| ge500_lt1000 | 0.0059% | 0.031× |
| ge1000_lt5000 | 0.0018% | 0.025× |

## §10 Top-prize escalation across modes — DESIGN_PHILOSOPHY §7

> **Source**: §3 per-mode lookup for top-jackpot pay_ids. M15 top family = `wild_pure` (pay_id 1, 200× pure 3-doublediamond) + `high7_*` (pay_id 2 wild-boosted / pay_id 21 pure 3-high7, 30×).
>
> **Universal direction**: m5 > m2 > m1 ≈ m7 in cadence (1 in N).

### pay_id 1 (wild_pure)

| mode | P(hit) | 1 in N | RTP pp |
|---|---:|---:|---:|
| 1 | 0.00166% | 60,141 | 0.3326 |
| 2 | 0.01351% | 7,401 | 2.7023 |
| 5 | 0.01351% | 7,401 | 2.7023 |
| 7 | 0.00178% | 56,070 | 0.3567 |

### pay_id 21 (high7_pure)

| mode | P(hit) | 1 in N | RTP pp |
|---|---:|---:|---:|
| 1 | 0.00299% | 33,411 | 0.0898 |
| 2 | 0.12511% | 799 | 3.7532 |
| 5 | 0.12511% | 799 | 3.7532 |
| 7 | 0.00321% | 31,150 | 0.0963 |

### pay_id 2 (high7_wild)

| mode | P(hit) | 1 in N | RTP pp |
|---|---:|---:|---:|
| 1 | 0.01366% | 7,319 | 1.1893 |
| 2 | 0.27774% | 360 | 22.0691 |
| 5 | 0.27774% | 360 | 22.0691 |
| 7 | 0.01465% | 6,824 | 1.2757 |

**Note** (user_brief.md default decision): M15 follows a 'dense mid-high, rare top' deviation from §7. The top jackpot cadence is intentionally tame (~1/60k in mode 1) per user brief — Designer must cite this in DESIGN.md.

## §11 Cross-mode invariants — DESIGN_PHILOSOPHY §9 / universal §C/D

> **Source**: §1 cross-mode comparisons. Each check is a directional lock (per §9 + memory/project_slot_designer.md §C/D).

| invariant | result | detail |
|---|:---:|---|
| `mode2_rtp_gt_mode1_rtp` | ✓ | m2 RTP = 294.28%, m1 RTP = 94.98% |
| `mode5_rtp_gt_mode2_rtp` | ✓ | m5 RTP = 490.32%, m2 RTP = 294.28% |
| `mode7_rtp_lt_mode1_rtp` | ✓ | m7 RTP = 85.09%, m1 RTP = 94.98% |
| `LUCKY_MONO_mode2_hit_gt_mode1` | ✓ | m2 hit = 29.35%, m1 hit = 19.31% |
| `mode5_hit_ge_mode2_hit` | ✓ | m5 hit = 29.35%, m2 hit = 29.35% |
| `MODE7_LOCK_mode7_hit_lt_mode1` | ✓ | m7 hit = 14.92%, m1 hit = 19.31% |
| `MODE5_BASE_LOCK_base_rtp_equal_to_mode2` | ✓ | |m5_base - m2_base| = 0.0000pp |
| `CV_TREND_mode7_cv_ge_mode1` | ✓ | m7 CV = 7.067, m1 CV = 5.765 |
| `CV_TREND_mode2_cv_le_mode1` | ✓ | m2 CV = 5.139, m1 CV = 5.765 |
| `FEATURE_mode2_trigger_ge_mode1` | ✓ | m2 trig = 2.692%, m1 trig = 1.127% |
| `FEATURE_mode5_trigger_ge_mode2` | ✓ | m5 trig = 2.692%, m2 trig = 2.692% |
| `MODE7_LOCK_trigger_equal_to_mode1` | ✗ | |m7_trig - m1_trig| = 0.000454pp |

## §12 Schema fingerprint — virtual vs production

> **Source**: `core/emitter/chunk.compute_schema_fingerprint` (sha256[:16] of sorted first-round key set). `compute_schema_fingerprint_for(engine, mode=...)` runs the engine with seeded RNG to produce a virtual first-round dict; production fp comes from the chunk envelope `_upstream_schema_fingerprint`.

| mode | virtual_fp | prod_fp (envelope) | prod_fp (recomputed from chunk) | match envelope | match recomputed |
|---|---|---|---|:---:|:---:|
| 1 | `5d02773c069fc396` | `5d02773c069fc396` | `5d02773c069fc396` | ✓ | ✓ |
| 2 | `5d02773c069fc396` | `5d02773c069fc396` | `5d02773c069fc396` | ✓ | ✓ |
| 5 | `5d02773c069fc396` | `5d02773c069fc396` | `5d02773c069fc396` | ✓ | ✓ |
| 7 | `5d02773c069fc396` | `5d02773c069fc396` | `5d02773c069fc396` | ✓ | ✓ |

**NB**: The fingerprint covers only the **base ST=1 round's** key set (because `compute_schema_fingerprint` hashes only the first round dict). The full chunk schema (envelope + ST=14/15 sub-rounds + analysisResult shape) was verified byte-level at refactor merge `2ae5a7d` (per SESSION_BRIEF §1 Stage 2). This section's match is a sanity-tight `first_round` proxy.

---

## Meta

- Generated by: `session_artifacts\M15\scripts\baseline_dump.py`
- Generated at: 2026-05-11T00:26:28Z
- Inputs read:
  - `slot_designer\machines\M15\spec.json`
  - `slot_designer\machines\M15\reel_strips.json`
  - `slot_designer\machines\M15\weights\mode_1\weights.json`
  - `slot_designer\machines\M15\weights\mode_2\weights.json`
  - `slot_designer\machines\M15\weights\mode_5\weights.json`
  - `slot_designer\machines\M15\weights\mode_7\weights.json`
- Companion machine-readable dump: `01b_baseline.json` (same directory)

**Next stage** (per ONBOARDING_PROCESS.md §5): Designer (D) reads this report + `user_brief.md` + R's `01d_research.md` → drafts `design_v0.md` + `targets_v0/` in Stage 4. Designer **must NOT** read `spec.json._design` / `weights.json._tuned_summary` / `weights.json.feature_params._analytic` blocks (stale narrative; see process_improvements.md #2 + #3).

