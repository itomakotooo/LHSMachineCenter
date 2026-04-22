# Tune report

target: **M1_mode7_low_rtp** — RTP 83.00%, CV 5.904


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 94.292 | 82.988 | 83.000 | -0.012 |
| hit_rate | 0.155 | 0.101 | 0.098 | 0.003 |
| CV | 5.655 | 5.939 | 5.904 | 0.035 |
| std_return_x | 5.332 | 4.928 | 4.900 | 0.028 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 565.0712 | 1.0840 |
| rtp   | 510.0817 | 0.0006 |
| shape | 1.0830 | 0.2963 |
| cv    | 6.1880 | 0.1229 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | ✓ |
| ge200_lt500 | 0.0041 | 0.0038 | 0.0040 | ✓ |
| ge100_lt200 | 0.0294 | 0.0122 | 0.0220 | ✓ |
| ge50_lt100 | 0.0900 | 0.0633 | 0.1360 | ✓ |
| ge20_lt50 | 0.9911 | 1.0202 | 0.9200 | ✓ |
| ge10_lt20 | 2.0835 | 2.1470 | 2.1700 | ✓ |
| ge5_lt10 | 2.6162 | 2.0404 | 1.5000 | ✓ |
| ge1_lt5 | 9.7026 | 4.7871 | 5.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 156→137 ↓19 | 156→159 ↑3 | 98→97 ↓1 |
| Bar2 | 102→88 ↓14 | 172→136 ↓36 | 164→130 ↓34 |
| Bar3 | 3→1 ↓2 | 71→39 ↓32 | 35→50 ↑15 |
| Blank | 500→505 ↑5 | 479→476 ↓3 | 507→529 ↑22 |
| Cherry | 21→14 ↓7 | 14→7 ↓7 | 62→25 ↓37 |
| Diamond1 | 90→104 ↑14 | 1→1 =0 | 1→1 =0 |
| Diamond2 | 116→145 ↑29 | 1→1 =0 | 1→1 =0 |
| Seven1 | 64→81 ↑17 | 36→2 ↓34 | 46→38 ↓8 |
| Seven2 | 64→67 ↑3 | 1→1 =0 | 30→29 ↓1 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.0676% | 0.0676% | +0.0000pp |
| avg blank-adj to high-value  | 1.0000 | 1.0000 | +0.0000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 38.856 | 38.856 |
| Diamond2 | 33.471 | 33.471 |
| Seven1 | 23.919 | 23.919 |
| Seven2 | 22.084 | 22.084 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0014 | 0.0014 |
| Diamond2 | 0.0017 | 0.0017 |
| Seven1 | 0.0500 | 0.0500 |
| Seven2 | 0.0145 | 0.0145 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 2 | 0.0000 | 0.0000 |
| 3 | 0.0001 | 0.0001 |
| 5 | 0.0026 | 0.0034 |
| 6 | 0.0501 | 0.0061 |
| 7 | 0.0575 | 0.0630 |
| 8 | 0.9069 | 0.7265 |
| 9 | 0.5831 | 0.7281 |
| 10 | 0.0508 | 0.0066 |
| 11 | 4.1613 | 3.7529 |
| 12 | 0.0019 | 0.0003 |
| 13 | 0.2451 | 0.0673 |
| 14 | 9.4576 | 4.7199 |