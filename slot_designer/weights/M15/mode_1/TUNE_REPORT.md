# Tune report

target: **M15_mode1_classic_base_v5** — RTP 42.75%, CV 5.848


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 68.316 | 42.758 | 42.750 | 0.008 |
| hit_rate | 0.143 | 0.131 | 0.134 | -0.003 |
| CV | 4.450 | 5.846 | 5.848 | -0.002 |
| std_return_x | 3.040 | 2.500 | 2.500 | -0.000 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 2683.2822 | 3.3092 |
| rtp   | 2614.5705 | 0.0002 |
| shape | 4.3808 | 1.5771 |
| cv    | 195.5621 | 0.0003 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge200_lt500 | 0.0006 | 0.0006 | 0.0200 | ✓ |
| ge100_lt200 | 0.0013 | 0.0145 | 0.0800 | ✓ |
| ge50_lt100 | 0.0074 | 0.0270 | 0.0800 | ✓ |
| ge20_lt50 | 1.1040 | 0.2845 | 0.4000 | ✓ |
| ge10_lt20 | 1.2897 | 0.6957 | 0.8000 | ✓ |
| ge5_lt10 | 0.3364 | 1.0610 | 2.0000 | ✓ |
| ge1_lt5 | 11.5649 | 10.9755 | 8.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 229→217 ↓12 | 123→66 ↓57 | 8→2 ↓6 |
| Bar2 | 198→130 ↓68 | 236→168 ↓68 | 278→157 ↓121 |
| Bar3 | 159→255 ↑96 | 185→255 ↑70 | 160→233 ↑73 |
| Blank | 529→546 ↑17 | 500→473 ↓27 | 557→609 ↑52 |
| Bonus | 0→0 =0 | 0→0 =0 | 2→18 ↑16 |
| Cherry | 2→17 ↑15 | 2→12 ↑10 | 2→12 ↑10 |
| High7 | 7→7 =0 | 3→70 ↑67 | 2→67 ↑65 |
| Wild | 88→71 ↓17 | 97→42 ↓55 | 1→3 ↑2 |

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
| 2 | 0.0006 | 0.0006 |
| 7 | 0.7988 | 1.5368 |
| 8 | 1.8935 | 0.4538 |
| 9 | 0.0441 | 0.0099 |
| 10 | 0.0014 | 0.0405 |
| 11 | 11.0293 | 7.4966 |
| 12 | 0.0000 | 0.0002 |
| 13 | 0.0010 | 0.0416 |
| 14 | 0.5356 | 3.4789 |