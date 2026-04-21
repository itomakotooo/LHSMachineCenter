# Tune report

target: **M14_mode1_devregen_110k** — RTP 93.49%, CV 4.938


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 76.932 | 93.490 | 93.488 | 0.002 |
| hit_rate | 0.181 | 0.153 | 0.209 | -0.056 |
| CV | 9.157 | 5.056 | 4.938 | 0.117 |
| std_return_x | 7.045 | 4.727 | 4.617 | 0.110 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 1648.2012 | 1.0682 |
| rtp   | 1096.3745 | 0.0000 |
| shape | 3.3477 | 0.5228 |
| cv    | 1779.8347 | 1.3801 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0001 | 0.0000 | 0.0000 | ✓ |
| ge200_lt500 | 0.0233 | 0.0015 | 0.0000 | ✓ |
| ge100_lt200 | 0.0663 | 0.0101 | 0.0091 | ✓ |
| ge50_lt100 | 0.1543 | 0.1123 | 0.1573 | ✓ |
| ge20_lt50 | 0.4418 | 0.8840 | 0.9218 | ✓ |
| ge10_lt20 | 0.7920 | 2.3012 | 1.7109 | ✓ |
| ge5_lt10 | 2.5181 | 3.3776 | 1.6664 | ✓ |
| ge1_lt5 | 14.1163 | 8.6093 | 6.4700 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 9.9173 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 110→123 ↑13 | 110→139 ↑29 | 150→141 ↓9 |
| Bar2 | 100→132 ↑32 | 100→158 ↑58 | 110→133 ↑23 |
| Bar3 | 80→28 ↓52 | 80→71 ↓9 | 90→104 ↑14 |
| Blank | 500→512 ↑12 | 500→487 ↓13 | 500→503 ↑3 |
| Cherry | 50→27 ↓23 | 50→19 ↓31 | 50→42 ↓8 |
| Diamond1 | 10→77 ↑67 | 10→1 ↓9 | 10→1 ↓9 |
| Diamond2 | 20→117 ↑97 | 20→1 ↓19 | 10→1 ↓9 |
| Seven1 | 90→88 ↓2 | 90→27 ↓63 | 40→1 ↓39 |
| Seven2 | 50→81 ↑31 | 50→1 ↓49 | 50→13 ↓37 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.0402% | 0.0473% | +0.0071pp |
| avg blank-adj to high-value  | 1.0000 | 0.8000 | -0.2000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 54.022 | 40.554 |
| Diamond2 | 40.510 | 38.852 |
| Seven1 | 22.898 | 26.887 |
| Seven2 | 22.127 | 27.809 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0012 | 0.0009 |
| Diamond2 | 0.0014 | 0.0013 |
| Seven1 | 0.0310 | 0.0366 |
| Seven2 | 0.0066 | 0.0084 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 2 | 0.0001 | 0.0000 |
| 3 | 0.0013 | 0.0001 |
| 5 | 0.0417 | 0.0012 |
| 6 | 0.0821 | 0.0024 |
| 7 | 0.1274 | 0.1707 |
| 8 | 0.2115 | 0.7000 |
| 9 | 0.3217 | 0.6353 |
| 10 | 0.1830 | 0.0137 |
| 11 | 3.0150 | 5.1612 |
| 12 | 0.0121 | 0.0021 |
| 13 | 0.6988 | 0.2374 |
| 14 | 13.4174 | 8.3719 |