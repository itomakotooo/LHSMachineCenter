# Tune report

target: **M15_mode1_classic_base** — RTP 67.50%, CV 4.444


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 42.197 | 67.428 | 67.500 | -0.072 |
| hit_rate | 0.222 | 0.139 | 0.134 | 0.005 |
| CV | 4.210 | 4.489 | 4.444 | 0.044 |
| std_return_x | 1.777 | 3.027 | 3.000 | 0.027 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 2686.1781 | 9.9187 |
| rtp   | 2560.9354 | 0.0205 |
| shape | 4.4563 | 4.7502 |
| cv    | 5.4838 | 0.1968 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge200_lt500 | 0.0001 | 0.0006 | 0.0250 | ✓ |
| ge100_lt200 | 0.0005 | 0.0013 | 0.0800 | ✓ |
| ge50_lt100 | 0.0043 | 0.0073 | 0.0800 | ✓ |
| ge20_lt50 | 0.3701 | 1.0940 | 0.4000 | ✓ |
| ge10_lt20 | 0.2224 | 1.2780 | 0.9000 | ✓ |
| ge5_lt10 | 1.1309 | 0.3327 | 2.5000 | ✓ |
| ge1_lt5 | 20.4507 | 11.1963 | 9.5000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 140→229 ↑89 | 140→123 ↓17 | 140→8 ↓132 |
| Bar2 | 120→198 ↑78 | 120→236 ↑116 | 120→278 ↑158 |
| Bar3 | 112→159 ↑47 | 112→185 ↑73 | 84→160 ↑76 |
| Blank | 540→529 ↓11 | 540→500 ↓40 | 540→557 ↑17 |
| Bonus | 0→0 =0 | 0→0 =0 | 2→14 ↑12 |
| Cherry | 60→1 ↓59 | 60→1 ↓59 | 60→1 ↓59 |
| High7 | 24→7 ↓17 | 24→3 ↓21 | 24→2 ↓22 |
| Wild | 10→88 ↑78 | 10→97 ↑87 | 5→1 ↓4 |

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
| 2 | 0.0001 | 0.0006 |
| 7 | 0.1342 | 0.7915 |
| 8 | 0.2140 | 1.8763 |
| 9 | 0.3306 | 0.0437 |
| 10 | 0.0033 | 0.0014 |
| 11 | 4.4823 | 10.9290 |
| 12 | 0.0219 | 0.0000 |
| 13 | 1.0241 | 0.0002 |
| 14 | 15.9684 | 0.2674 |