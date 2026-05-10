# Tune report

target: **M1_mode2_lucky_classic_7_dominant** — RTP 294.50%, CV 5.501


## Baseline → Tuned

| metric | baseline | tuned | target | Δ to target |
|---|---|---|---|---|
| RTP % | 291.291 | 294.498 | 294.500 | -0.002 |
| hit_rate | 0.278 | 0.278 | 0.277 | 0.001 |
| CV | 4.096 | 5.516 | 5.501 | 0.016 |
| std_return_x | 11.931 | 16.246 | 16.200 | 0.046 |

## Cost breakdown

| cost | baseline | tuned |
|---|---|---|
| total | 245.0488 | 2.8688 |
| rtp   | 41.1821 | 0.0000 |
| shape | 4.2910 | 1.8890 |
| cv    | 197.4178 | 0.0242 |

## Bucket distribution (%)

| bucket | baseline | tuned | target | reachable |
|---|---|---|---|---|
| ge5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge1000_lt5000 | 0.0000 | 0.0000 | 0.0000 | — |
| ge500_lt1000 | 0.0006 | 0.0016 | 0.0000 | ✓ |
| ge200_lt500 | 0.0111 | 0.1317 | 0.2700 | ✓ |
| ge100_lt200 | 0.3055 | 0.3739 | 1.1000 | ✓ |
| ge50_lt100 | 0.9120 | 0.7742 | 0.0000 | ✓ |
| ge20_lt50 | 2.1746 | 1.5241 | 1.3000 | ✓ |
| ge10_lt20 | 4.9620 | 3.8381 | 2.5000 | ✓ |
| ge5_lt10 | 8.1122 | 6.5891 | 5.5000 | ✓ |
| ge1_lt5 | 11.2829 | 14.5233 | 17.0000 | ✓ |
| gt0_lt1 | 0.0000 | 0.0000 | 0.0000 | — |

## Count changes (per symbol × reel)

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 213→231 ↑18 | 88→106 ↑18 | 202→167 ↓35 |
| Bar2 | 147→143 ↓4 | 237→247 ↑10 | 118→124 ↑6 |
| Bar3 | 159→174 ↑15 | 143→187 ↑44 | 109→60 ↓49 |
| Blank | 328→350 ↑22 | 443→443 =0 | 408→436 ↑28 |
| Cherry | 68→126 ↑58 | 34→22 ↓12 | 14→21 ↑7 |
| Diamond1 | 1→10 ↑9 | 67→34 ↓33 | 102→67 ↓35 |
| Diamond2 | 1→17 ↑16 | 62→75 ↑13 | 81→74 ↓7 |
| Seven1 | 2→70 ↑68 | 27→21 ↓6 | 62→113 ↑51 |
| Seven2 | 1→9 ↑8 | 45→26 ↓19 | 1→19 ↑18 |

## Phase 5 — experience metrics (order optimization)

| metric | before | after | Δ |
|---|---|---|---|
| 2-of-3 near-miss rate (total) | 0.1166% | 0.1220% | +0.0053pp |
| avg blank-adj to high-value  | 1.0000 | 1.0000 | +0.0000 |

PWDF per high-value symbol (averaged across reels):

| symbol | before | after |
|---|---|---|
| Diamond1 | 3.397 | 2.951 |
| Diamond2 | 2.170 | 2.258 |
| Seven1 | 3.246 | 3.419 |
| Seven2 | 4.002 | 3.628 |

Near-miss rate per high-value symbol:

| symbol | before (%) | after (%) |
|---|---|---|
| Diamond1 | 0.0115 | 0.0094 |
| Diamond2 | 0.0233 | 0.0251 |
| Seven1 | 0.0789 | 0.0850 |
| Seven2 | 0.0028 | 0.0025 |

## Pay_id hit rates (analytic)

| pay_id | baseline % | tuned % |
|---|---|---|
| 2 | 0.0006 | 0.0016 |
| 3 | 0.0031 | 0.0210 |
| 5 | 0.0042 | 0.0256 |
| 6 | 0.0091 | 0.1966 |
| 7 | 1.1015 | 0.8140 |
| 8 | 1.4152 | 1.1016 |
| 9 | 1.5489 | 1.1754 |
| 10 | 0.0039 | 0.0669 |
| 11 | 12.3886 | 9.8259 |
| 12 | 0.0028 | 0.0041 |
| 13 | 0.3431 | 0.4524 |
| 14 | 10.9398 | 14.0709 |