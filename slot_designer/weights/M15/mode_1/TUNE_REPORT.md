# Tune report

target: **M15_mode1_classic_base_v5** — RTP 42.75%, CV 5.848


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 40.276 | 42.754 | 42.750 | 0.004 |
| hit_rate | 0.121 | 0.131 | 0.134 | -0.003 |
| CV | 6.413 | 5.839 | 5.848 | -0.009 |
| std_return_x | 2.583 | 2.496 | 2.500 | -0.004 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 41.1063 | 2.5193 |
| rtp   | 24.4766 | 0.0001 |
| shape | 2.3210 | 1.2102 |
| cv    | 31.9612 | 0.0086 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge200_lt500 | 0.0007 | 0.0002 | 0.0200 | ✓ |
| ge100_lt200 | 0.0161 | 0.0149 | 0.0800 | ✓ |
| ge50_lt100 | 0.0302 | 0.0373 | 0.0800 | ✓ |
| ge20_lt50 | 0.3161 | 0.2425 | 0.4000 | ✓ |
| ge10_lt20 | 0.6408 | 0.8012 | 0.8000 | ✓ |
| ge5_lt10 | 0.6822 | 1.2475 | 2.0000 | ✓ |
| ge1_lt5 | 10.4293 | 10.7831 | 8.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| 1bar | 191→222 ↑31 | 192→267 ↑75 | 233→285 ↑52 |
| 2bar | 130→137 ↑7 | 168→184 ↑16 | 157→100 ↓57 |
| 3bar | 217→190 ↓27 | 66→17 ↓49 | 3→1 ↓2 |
| blank | 546→495 ↓51 | 473→477 ↑4 | 609→621 ↑12 |
| cherry | 17→16 ↓1 | 12→9 ↓3 | 12→25 ↑13 |
| doublediamond | 71→85 ↑14 | 42→37 ↓5 | 3→1 ↓2 |
| high7 | 7→13 ↑6 | 70→88 ↑18 | 67→65 ↓2 |
| jackpot | 5→2 ↓3 | 5→2 ↓3 | 5→21 ↑16 |
| topdollar | 0→0 =0 | 0→0 =0 | 12→15 ↑3 |

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
| 1 | 0.0007 | 0.0002 |
| 2 | 0.0425 | 0.0514 |
| 3 | 0.0133 | 0.0019 |
| 4 | 0.0002 | 0.0003 |
| 5 | 0.5033 | 0.3483 |
| 7 | 1.0790 | 1.8769 |
| 8 | 6.8260 | 6.4864 |
| 9 | 3.6033 | 4.2967 |
| 21 | 0.0024 | 0.0052 |
| 71 | 0.0446 | 0.0595 |