# Tune report

target: **M37_mode1_classic_v1** — RTP 95.00%, CV 6.000


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 608.006 | 95.061 | 95.000 | 0.061 |
| hit_rate | 0.309 | 0.152 | 0.145 | 0.007 |
| CV | 6.583 | 6.687 | 6.000 | 0.687 |
| std_return_x | 40.028 | 6.357 | 5.700 | 0.657 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 1053325.4164 | 29.4013 |
| rtp   | 1052699.3500 | 0.0149 |
| shape | 3.6488 | 3.1378 |
| cv    | 34.0367 | 47.1697 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0860 | 0.0004 | 0.0025 | ✓ |
| ge500_lt1000 | 0.1019 | 0.0007 | 0.0030 | ✓ |
| ge200_lt500 | 0.1401 | 0.0034 | 0.0150 | ✓ |
| ge100_lt200 | 3.0857 | 0.2627 | 0.0600 | ✓ |
| ge50_lt100 | 0.2887 | 0.0160 | 0.0700 | ✓ |
| ge20_lt50 | 0.4671 | 0.0705 | 0.7000 | ✓ |
| ge10_lt20 | 4.4030 | 3.6556 | 1.8000 | ✓ |
| ge5_lt10 | 4.1525 | 3.1328 | 2.0000 | ✓ |
| ge1_lt5 | 18.1662 | 8.0640 | 10.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| 1bar | 6→29 ↑23 | 4→54 ↑50 | 6→3 ↓3 |
| 2bar | 6→7 ↑1 | 4→62 ↑58 | 6→3 ↓3 |
| 3bar | 6→3 ↓3 | 4→13 ↑9 | 6→3 ↓3 |
| 7bar | 6→3 ↓3 | 4→39 ↑35 | 6→3 ↓3 |
| blank | 54→78 ↑24 | 54→109 ↑55 | 54→135 ↑81 |
| grand | 0→0 =0 | 3→1 ↓2 | 0→0 =0 |
| high7 | 9→3 ↓6 | 9→68 ↑59 | 9→3 ↓6 |
| major | 0→0 =0 | 4→14 ↑10 | 0→0 =0 |
| mini | 0→0 =0 | 2→12 ↑10 | 0→0 =0 |
| minor | 0→0 =0 | 4→12 ↑8 | 0→0 =0 |
| wild | 9→3 ↓6 | 0→0 =0 | 9→3 ↓6 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.0000% | 0.0000% | +0.0000pp |
| avg blank-adj to high-value  | 0.0000 | 0.0000 | +0.0000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 0.000 | 0.000 |
| Diamond2 | 0.000 | 0.000 |
| Seven1 | 0.000 | 0.000 |
| Seven2 | 0.000 | 0.000 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0000 | 0.0000 |
| Diamond2 | 0.0000 | 0.0000 |
| Seven1 | 0.0000 | 0.0000 |
| Seven2 | 0.0000 | 0.0000 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 1 | 0.7165 | 0.0473 |
| 2 | 0.3269 | 0.0332 |
| 3 | 0.3269 | 0.0205 |
| 4 | 0.3269 | 0.0771 |
| 5 | 0.3269 | 0.2365 |
| 6 | 0.5987 | 0.0745 |
| 7 | 2.2928 | 1.5154 |
| 8 | 2.7800 | 0.2508 |
| 9 | 23.0999 | 12.9462 |
| 102 | 0.0382 | 0.0017 |
| 103 | 0.0382 | 0.0015 |
| 104 | 0.0191 | 0.0015 |