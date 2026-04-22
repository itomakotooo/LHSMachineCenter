# Tune report

target: **M1_mode7_low_rtp** — RTP 80.95%, CV 6.300


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 94.292 | 80.900 | 80.950 | -0.050 |
| hit_rate | 0.155 | 0.079 | 0.077 | 0.002 |
| CV | 5.655 | 6.311 | 6.300 | 0.011 |
| std_return_x | 5.332 | 5.106 | 5.100 | 0.006 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 829.8802 | 0.7702 |
| rtp   | 712.0886 | 0.0102 |
| shape | 3.2307 | 0.4736 |
| cv    | 41.6447 | 0.0122 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | ✓ |
| ge200_lt500 | 0.0041 | 0.0033 | 0.0050 | ✓ |
| ge100_lt200 | 0.0294 | 0.0234 | 0.0250 | ✓ |
| ge50_lt100 | 0.0900 | 0.0533 | 0.1500 | ✓ |
| ge20_lt50 | 0.9911 | 0.9723 | 1.0000 | ✓ |
| ge10_lt20 | 2.0835 | 1.9447 | 2.0000 | ✓ |
| ge5_lt10 | 2.6162 | 2.0702 | 1.5000 | ✓ |
| ge1_lt5 | 9.7026 | 2.7833 | 3.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 156→114 ↓42 | 156→147 ↓9 | 98→113 ↑15 |
| Bar2 | 102→90 ↓12 | 172→152 ↓20 | 164→147 ↓17 |
| Bar3 | 3→1 ↓2 | 71→73 ↑2 | 35→9 ↓26 |
| Blank | 500→512 ↑12 | 479→490 ↑11 | 507→515 ↑8 |
| Cherry | 21→14 ↓7 | 14→7 ↓7 | 62→6 ↓56 |
| Diamond1 | 90→52 ↓38 | 1→1 =0 | 1→1 =0 |
| Diamond2 | 116→139 ↑23 | 1→1 =0 | 1→1 =0 |
| Seven1 | 64→75 ↑11 | 36→23 ↓13 | 46→33 ↓13 |
| Seven2 | 64→68 ↑4 | 1→18 ↑17 | 30→1 ↓29 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.0874% | 0.0874% | +0.0000pp |
| avg blank-adj to high-value  | 1.0000 | 1.0000 | +0.0000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 34.019 | 34.019 |
| Diamond2 | 37.477 | 37.477 |
| Seven1 | 4.675 | 4.675 |
| Seven2 | 15.760 | 15.760 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0006 | 0.0006 |
| Diamond2 | 0.0019 | 0.0019 |
| Seven1 | 0.0781 | 0.0781 |
| Seven2 | 0.0067 | 0.0067 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 2 | 0.0000 | 0.0000 |
| 3 | 0.0001 | 0.0001 |
| 5 | 0.0026 | 0.0018 |
| 6 | 0.0501 | 0.0289 |
| 7 | 0.0575 | 0.0196 |
| 8 | 0.9069 | 0.8036 |
| 9 | 0.5831 | 0.6513 |
| 10 | 0.0508 | 0.0336 |
| 11 | 4.1613 | 3.5281 |
| 12 | 0.0019 | 0.0001 |
| 13 | 0.2451 | 0.0250 |
| 14 | 9.4576 | 2.7583 |