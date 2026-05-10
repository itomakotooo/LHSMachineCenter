# Tune report

target: **M1_mode1_classic_7_dominant** — RTP 94.30%, CV 5.620


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 94.310 | 94.303 | 94.300 | 0.003 |
| hit_rate | 0.151 | 0.155 | 0.152 | 0.003 |
| CV | 5.628 | 5.656 | 5.620 | 0.036 |
| std_return_x | 5.308 | 5.334 | 5.300 | 0.034 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 4.1489 | 3.5821 |
| rtp   | 0.0004 | 0.0000 |
| shape | 1.3770 | 1.1113 |
| cv    | 0.0055 | 0.1295 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | ✓ |
| ge200_lt500 | 0.0040 | 0.0041 | 0.0600 | ✓ |
| ge100_lt200 | 0.0203 | 0.0294 | 0.2400 | ✓ |
| ge50_lt100 | 0.1356 | 0.0901 | 0.0000 | ✓ |
| ge20_lt50 | 0.9205 | 0.9917 | 0.6000 | ✓ |
| ge10_lt20 | 2.1655 | 2.0852 | 1.3000 | ✓ |
| ge5_lt10 | 2.6500 | 2.6067 | 2.5000 | ✓ |
| ge1_lt5 | 9.2451 | 9.7042 | 10.5000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 161→156 ↓5 | 116→156 ↑40 | 112→98 ↓14 |
| Bar2 | 113→102 ↓11 | 157→172 ↑15 | 135→164 ↑29 |
| Bar3 | 7→2 ↓5 | 74→71 ↓3 | 69→35 ↓34 |
| Blank | 517→500 ↓17 | 493→479 ↓14 | 496→507 ↑11 |
| Cherry | 15→21 ↑6 | 29→14 ↓15 | 46→62 ↑16 |
| Diamond1 | 100→90 ↓10 | 1→1 =0 | 1→1 =0 |
| Diamond2 | 138→116 ↓22 | 1→1 =0 | 1→1 =0 |
| Seven1 | 71→64 ↓7 | 48→36 ↓12 | 7→46 ↑39 |
| Seven2 | 71→64 ↓7 | 6→1 ↓5 | 32→30 ↓2 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.1028% | 0.1014% | -0.0013pp |
| avg blank-adj to high-value  | 1.0000 | 1.0000 | +0.0000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 40.593 | 39.185 |
| Diamond2 | 36.810 | 33.520 |
| Seven1 | 3.654 | 3.682 |
| Seven2 | 25.495 | 21.965 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0011 | 0.0011 |
| Diamond2 | 0.0013 | 0.0012 |
| Seven1 | 0.0860 | 0.0869 |
| Seven2 | 0.0144 | 0.0123 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 2 | 0.0000 | 0.0000 |
| 3 | 0.0001 | 0.0001 |
| 5 | 0.0084 | 0.0026 |
| 6 | 0.0139 | 0.0502 |
| 7 | 0.1332 | 0.0572 |
| 8 | 0.7706 | 0.9078 |
| 9 | 0.5409 | 0.5836 |
| 10 | 0.0656 | 0.0509 |
| 11 | 4.3612 | 4.1530 |
| 12 | 0.0020 | 0.0019 |
| 13 | 0.2581 | 0.2452 |
| 14 | 8.9870 | 9.4590 |