# Tune report

target: **M37_mode2_lucky_v1** — RTP 300.00%, CV 5.000


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 94.951 | 299.914 | 300.000 | -0.086 |
| hit_rate | 0.152 | 0.230 | 0.225 | 0.005 |
| CV | 6.683 | 5.388 | 5.000 | 0.388 |
| std_return_x | 6.346 | 16.159 | 12.000 | 4.159 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 168379.4982 | 15.2253 |
| rtp   | 168180.7028 | 0.0296 |
| shape | 3.1459 | 5.0729 |
| cv    | 283.3504 | 15.0375 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0004 | 0.0022 | 0.0040 | ✓ |
| ge500_lt1000 | 0.0007 | 0.0044 | 0.0050 | ✓ |
| ge200_lt500 | 0.0034 | 0.0350 | 0.0250 | ✓ |
| ge100_lt200 | 0.2627 | 1.8577 | 0.1000 | ✓ |
| ge50_lt100 | 0.0158 | 0.0193 | 0.1200 | ✓ |
| ge20_lt50 | 0.0696 | 0.1495 | 1.2000 | ✓ |
| ge10_lt20 | 3.6554 | 5.1763 | 3.1000 | ✓ |
| ge5_lt10 | 3.1327 | 4.7309 | 3.4000 | ✓ |
| ge1_lt5 | 8.0279 | 11.0437 | 17.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| 1bar | 29→39 ↑10 | 54→42 ↓12 | 3→3 =0 |
| 2bar | 7→3 ↓4 | 62→71 ↑9 | 3→27 ↑24 |
| 3bar | 3→3 =0 | 13→22 ↑9 | 3→3 =0 |
| 7bar | 3→3 =0 | 39→34 ↓5 | 3→3 =0 |
| blank | 78→91 ↑13 | 109→108 ↓1 | 137→119 ↓18 |
| grand | 0→0 =0 | 1→8 ↑7 | 0→0 =0 |
| high7 | 3→3 =0 | 68→75 ↑7 | 3→3 =0 |
| major | 0→0 =0 | 14→22 ↑8 | 0→0 =0 |
| mini | 0→0 =0 | 12→21 ↑9 | 0→0 =0 |
| minor | 0→0 =0 | 12→20 ↑8 | 0→0 =0 |
| wild | 3→3 =0 | 0→0 =0 | 3→3 =0 |

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
| 1 | 0.0467 | 0.0468 |
| 2 | 0.0328 | 0.0318 |
| 3 | 0.0203 | 0.0274 |
| 4 | 0.0761 | 0.2524 |
| 5 | 0.2334 | 0.2819 |
| 6 | 0.0736 | 0.0626 |
| 7 | 1.4959 | 4.2341 |
| 8 | 0.2509 | 1.7272 |
| 9 | 12.9344 | 16.3491 |
| 102 | 0.0017 | 0.0020 |
| 103 | 0.0014 | 0.0018 |
| 104 | 0.0014 | 0.0019 |