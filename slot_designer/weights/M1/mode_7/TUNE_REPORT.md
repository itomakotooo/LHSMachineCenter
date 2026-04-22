# Tune report

target: **M1_mode7_low_rtp** — RTP 82.65%, CV 5.929


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 80.883 | 82.668 | 82.650 | 0.018 |
| hit_rate | 0.079 | 0.098 | 0.097 | 0.001 |
| CV | 6.308 | 5.947 | 5.929 | 0.019 |
| std_return_x | 5.102 | 4.916 | 4.900 | 0.016 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 27.2047 | 0.3028 |
| rtp   | 12.4841 | 0.0013 |
| shape | 1.7297 | 0.1741 |
| cv    | 14.3560 | 0.0344 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | ✓ |
| ge200_lt500 | 0.0033 | 0.0027 | 0.0050 | ✓ |
| ge100_lt200 | 0.0233 | 0.0132 | 0.0250 | ✓ |
| ge50_lt100 | 0.0533 | 0.0819 | 0.1500 | ✓ |
| ge20_lt50 | 0.9706 | 1.0058 | 1.0000 | ✓ |
| ge10_lt20 | 1.9413 | 2.0070 | 2.0000 | ✓ |
| ge5_lt10 | 2.0910 | 1.8699 | 1.5000 | ✓ |
| ge1_lt5 | 2.7808 | 4.8239 | 5.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 114→111 ↓3 | 147→161 ↑14 | 113→142 ↑29 |
| Bar2 | 90→73 ↓17 | 152→172 ↑20 | 147→88 ↓59 |
| Bar3 | 3→1 ↓2 | 73→61 ↓12 | 9→21 ↑12 |
| Blank | 512→478 ↓34 | 490→517 ↑27 | 515→521 ↑6 |
| Cherry | 14→29 ↑15 | 7→19 ↑12 | 6→1 ↓5 |
| Diamond1 | 52→42 ↓10 | 1→7 ↑6 | 1→1 =0 |
| Diamond2 | 139→156 ↑17 | 1→1 =0 | 1→1 =0 |
| Seven1 | 75→115 ↑40 | 23→5 ↓18 | 33→8 ↓25 |
| Seven2 | 68→49 ↓19 | 18→4 ↓14 | 1→2 ↑1 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.0315% | 0.0327% | +0.0012pp |
| avg blank-adj to high-value  | 1.0000 | 1.0000 | +0.0000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 20.794 | 24.968 |
| Diamond2 | 38.453 | 38.457 |
| Seven1 | 15.347 | 15.421 |
| Seven2 | 13.276 | 17.289 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0022 | 0.0027 |
| Diamond2 | 0.0022 | 0.0022 |
| Seven1 | 0.0252 | 0.0253 |
| Seven2 | 0.0018 | 0.0024 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 2 | 0.0000 | 0.0000 |
| 3 | 0.0001 | 0.0003 |
| 5 | 0.0018 | 0.0011 |
| 6 | 0.0289 | 0.0048 |
| 7 | 0.0198 | 0.0399 |
| 8 | 0.8021 | 0.5599 |
| 9 | 0.6501 | 0.9593 |
| 10 | 0.0335 | 0.0031 |
| 11 | 3.5465 | 3.4119 |
| 12 | 0.0001 | 0.0001 |
| 13 | 0.0250 | 0.0611 |
| 14 | 2.7559 | 4.7628 |