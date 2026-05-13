# Stage 1b — M43 production baseline (mode 1 only)

## Verdict (one-liner)
**pass** — 12 sections produced; §10/§11 N-A this session (mode 2/5/7 deferred per SESSION_BRIEF); §1/§2/§3 cross-signal sanity matches; §2 high-multiplier bucket share confirmed thin (matches user's '稀烂' assessment).

- machine: **M43**
- mode: **1**
- sample size: **650,000 paid rounds** (650k envelope; reading C:\Users\pangg\Documents\Projects\LHS\User_Managerment_GPT\rawdata\M43\mode_1)
- bet: **1000** credits/spin
- semantics: **paid-round (session-centric)** per `memory/feedback_paid_round_default.md` + `feedback_session_semantics.md`; respin/minigame wins attribute to triggering paid spin.

---

## §1 Per-mode totals

| metric | value | semantics |
|---|---|---|
| **RTP (paid-round, session-incl. respin+minigame)** | **93.2306%** | sum(session_win)/sum(bet) |
| Hit rate (session) | 14.1969% | paid rounds with non-zero session_win |
| Hit rate (base-spin only, no respin/mini) | 13.2765% | paid rounds where base spin won |
| std(return_x) per round | 3.8642 | population std on x = session_win/bet |
| CV (std/mean) | 4.1448 | std/mean |
| mean(return_x) on winning rounds | 6.5670 | average payout multiplier when you DO win |
| std(return_x) on winning rounds | 8.2568 | spread of winning amounts |
| miss_rate | 85.8031% | 1 - hit_rate (session) |
| total_prob sanity | 1.0000000000 | should be 1.000 |

Confidence: **HIGH** — direct rawdata aggregation across 650,000 paid rounds; cross-signal sanity passes (see §sanity).

## §2 Bucket distribution (11 buckets)

Bucket = paid-round (session-incl.) win/bet multiplier.

| bucket | rate% | RTP pp | count |
|---|---|---|---|
| gt0_lt1 | 0.0000% | 0.0000pp | 0 |
| ge1_lt2 | 0.0000% | 0.0000pp | 0 |
| ge2_lt5 | 7.2798% | 18.2455pp | 47,319 |
| ge5_lt10 | 3.7242% | 19.0249pp | 24,207 |
| ge10_lt20 | 1.9726% | 20.2502pp | 12,822 |
| ge20_lt50 | 1.1849% | 33.1212pp | 7,702 |
| ge50_lt100 | 0.0306% | 1.8757pp | 199 |
| ge100_lt200 | 0.0043% | 0.5762pp | 28 |
| ge200_lt500 | 0.0005% | 0.1369pp | 3 |
| ge500_lt1000 | 0.0000% | 0.0000pp | 0 |
| ge1000_lt5000 | 0.0000% | 0.0000pp | 0 |
| ge5000 | 0.0000% | 0.0000pp | 0 |
| **(sum)** | **14.1969%** (= hit_rate) | **93.2306pp** (= RTP%) | 92,280 |

**Per user (2026-05-13): bucket distribution is '稀烂' — high-multiplier share too thin.**

**Observed anomalies that match the user's 稀烂 critique**:
1. **High-multiplier (≥100×) total share**: rate 0.0048%, RTP 0.7131pp — i.e. only ~0.7pp out of ~93pp RTP comes from ≥100× hits.
   - This is < 0.5% hit rate for everything ≥100×, which is below archetype 1-line classic baseline (a 1-line classic typically lands 0.5-2% of paid rounds in ≥100× buckets — see `memory/reference_classic_slot_rtp_distribution.md`).
2. **Top-prize buckets (≥1000×)**: ge1000_lt5000 = 0.000000% / 0.0000pp; ge5000 = 0.000000% / 0.0000pp.
   - If both effectively 0, this means **no top-prize at all in 650k spins** — Lucky Ducky should have a top symbol payout (typically 3× 7 = 100×-300× minimum; ≥500× is reasonable jackpot).
3. **Mid buckets** (5×-50×) carry the RTP share — see breakdown above.

Confidence: **HIGH** — bucket counts sum to hit_rate exactly; RTP sums match §1 RTP.

## §3 Per pay_id breakdown

| pay_id | family | hits | 1 in N spins | avg win_x | RTP pp |
|---|---|---|---|---|---|
| 2 | wild_top | 14 | 1 in 46428.6 | 142.8571× | 0.3077pp |
| 3 | seven_top | 68 | 1 in 9558.8 | 79.4118× | 0.8308pp |
| 4 | bar3_top | 195 | 1 in 3333.3 | 48.0000× | 1.4400pp |
| 5 | bar2 | 524 | 1 in 1240.5 | 24.0076× | 1.9354pp |
| 6 | bar1 | 12,094 | 1 in 53.7 | 10.7996× | 20.0938pp |
| 7 | bar_mixed | 24,727 | 1 in 26.3 | 5.1618× | 19.6362pp |
| 8 | wild_blank | 912 | 1 in 712.7 | 7.4068× | 1.0392pp |
| 9 | small_consol | 50,208 | 1 in 12.9 | 2.4985× | 19.2994pp |
| **(sum)** | | 88,742 | | | **64.5825pp** |

**Observations for 稀烂 critique**:
- pay_id 4 (bar3 top, 40× base): only 195 hits across 650,000 spins → cadence ~1 in 3,333 → RTP 1.4400pp. Top family currently contributes very little to RTP.
- pay_id 9 (small_consol, 2× base): 50,208 hits → cadence 1 in 12.9 → RTP 19.2994pp (20.7% of total RTP). Small consolation pay dominates RTP.

Confidence: **HIGH** — pay_id breakdown is direct count from PayoutIdToWinAmount field on every paid+respin round.

## §4 Family RTP share

Pay_id aggregated into family groups (per §1c mechanism inference).

| family | hits | RTP pp | share% of total RTP |
|---|---|---|---|
| bar1 | 12,094 | 20.0938pp | 31.1135% |
| bar_mixed | 24,727 | 19.6362pp | 30.4048% |
| small_consol | 50,208 | 19.2994pp | 29.8833% |
| bar2 | 524 | 1.9354pp | 2.9968% |
| bar3_top | 195 | 1.4400pp | 2.2297% |
| wild_blank | 912 | 1.0392pp | 1.6092% |
| seven_top | 68 | 0.8308pp | 1.2864% |
| wild_top | 14 | 0.3077pp | 0.4764% |

Confidence: **HIGH** for grouping → families; **MED** for family semantics — see §1c inference (the family label is reverse-engineered from rawdata).

## §5 Per-reel marginals (mid-row, paid base spins only)

Marginal frequency of each symbol on the **center row** (the payline) per reel.

| reel | symbol | mid-row count | mid-row prob% |
|---|---|---|---|
| R1 | blank | 427,648 | 65.7920% |
| R1 | 1bar | 168,022 | 25.8495% |
| R1 | 2bar | 35,974 | 5.5345% |
| R1 | 3bar | 10,241 | 1.5755% |
| R1 | 7 | 5,117 | 0.7872% |
| R1 | blankup | 1,040 | 0.1600% |
| R1 | wild | 1,005 | 0.1546% |
| R1 | blankdown | 953 | 0.1466% |
| R2 | blank | 342,839 | 52.7445% |
| R2 | 1bar | 138,553 | 21.3158% |
| R2 | 3bar | 84,414 | 12.9868% |
| R2 | 2bar | 42,213 | 6.4943% |
| R2 | blankup | 12,072 | 1.8572% |
| R2 | wild | 11,968 | 1.8412% |
| R2 | blankdown | 11,929 | 1.8352% |
| R2 | 7 | 6,012 | 0.9249% |
| R3 | blank | 405,995 | 62.4608% |
| R3 | 1bar | 152,214 | 23.4175% |
| R3 | 2bar | 42,192 | 6.4911% |
| R3 | 3bar | 24,350 | 3.7462% |
| R3 | blankup | 9,035 | 1.3900% |
| R3 | blankdown | 8,968 | 1.3797% |
| R3 | 7 | 6,067 | 0.9334% |
| R3 | wild | 1,179 | 0.1814% |

Confidence: **HIGH** — direct count from StopSymbolsByCol mid-row.

## §6 Reel asymmetry (R1 vs R3) per DESIGN_PHILOSOPHY §12

Per Reid/Harrigan: classic slots often place more blanks on R1 (build anticipation) and more high-symbol on R3 (near-miss).

| symbol | R1 mid% | R3 mid% | R1 any-row% | R3 any-row% | direction (mid) |
|---|---|---|---|---|---|
| blank | 65.7920% | 62.4608% | 40.3623% | 39.6656% | R1>R3 |
| blankdown | 0.1466% | 1.3797% | 4.0363% | 4.5771% | R3>R1 |
| blankup | 0.1600% | 1.3900% | 0.2353% | 0.6804% | R3>R1 |
| wild | 0.1546% | 0.1814% | 0.1537% | 0.9837% | ~equal |
| 7 | 0.7872% | 0.9334% | 8.4014% | 8.8515% | R3>R1 |
| 3bar | 1.5755% | 3.7462% | 11.4707% | 14.3184% | R3>R1 |
| 2bar | 5.5345% | 6.4911% | 13.0760% | 13.3628% | R3>R1 |
| 1bar | 25.8495% | 23.4175% | 22.2644% | 17.5604% | R1>R3 |

**Note**: M43 strips have **identical symbol vocabulary and 14-triple inventory** across R1/R2/R3 (same 16-stop layout), but the **stop-frequency weighting differs significantly per reel** — most notably the `wild` stop's marginal probability on R2 (≈1.84%) is ~12× that of R1 (≈0.15%) and R3 (≈0.18%). This is a **weighted-strip asymmetry**, not a structural asymmetry. The R2 wild concentration is the classic Lucky Ducky signature: wild on R2 is the "duck reel" — visually attractive and frequent on the middle reel, but contributes mostly to the 2× small consolation pay (pay_id 9) on its own.

Differences in `1bar` between R1 (25.85%) and R3 (23.42%) are also large enough (~2.4pp) to be intentional weighting, not noise (650k sample → noise floor ≪ 0.1pp).

Confidence: **HIGH** — direct count comparison; weighted-strip asymmetry confirmed.

## §7 Window visibility (PWDF) per DESIGN_PHILOSOPHY §15

any-row visibility vs mid-row (payline) probability. Ratio > 3 means symbol is much more visible than it pays ("window tease").

| symbol | reel | mid-row% | any-row% | any/mid ratio |
|---|---|---|---|---|
| 7 | R1 | 0.7872% | 8.4014% | 10.67 |
| 7 | R2 | 0.9249% | 8.9330% | 9.66 |
| 7 | R3 | 0.9334% | 8.8515% | 9.48 |
| wild | R1 | 0.1546% | 0.1537% | 0.99 |
| wild | R2 | 1.8412% | 1.8446% | 1.00 |
| wild | R3 | 0.1814% | 0.9837% | 5.42 |
| 3bar | R1 | 1.5755% | 11.4707% | 7.28 |
| 3bar | R2 | 12.9868% | 15.7583% | 1.21 |
| 3bar | R3 | 3.7462% | 14.3184% | 3.82 |
| 2bar | R1 | 5.5345% | 13.0760% | 2.36 |
| 2bar | R2 | 6.4943% | 10.2139% | 1.57 |
| 2bar | R3 | 6.4911% | 13.3628% | 2.06 |
| 1bar | R1 | 25.8495% | 22.2644% | 0.86 |
| 1bar | R2 | 21.3158% | 15.3958% | 0.72 |
| 1bar | R3 | 23.4175% | 17.5604% | 0.75 |
| blank | R1 | 65.7920% | 40.3623% | 0.61 |
| blank | R2 | 52.7445% | 42.1452% | 0.80 |
| blank | R3 | 62.4608% | 39.6656% | 0.64 |

Confidence: **HIGH** for raw numbers; **MED** for interpretation (3-row window is observed; physical reel positions inferred to be 16-stop per §1c Euler reconstruction).

## §8 Blank-flank audit (DESIGN_PHILOSOPHY §13)

Audit for X-Blank-X patterns (same non-blank symbol top+bottom flanking a blank mid). High-frequency repeats violate the diversity guideline.

| reel | violation count | violation rate% | total triples | examples |
|---|---|---|---|---|
| R1 | 50,969 | 7.8414% | 650,000 | ('1bar', 'blank', '1bar')×50969 |
| R2 | 29,770 | 4.5800% | 650,000 | ('1bar', 'blank', '1bar')×29770 |
| R3 | 30,110 | 4.6323% | 650,000 | ('1bar', 'blank', '1bar')×30110 |

**Note**: triples like (`1bar`, `blank`, `1bar`) qualify as X-Blank-X violations. These are repeated on the strip per the Euler reconstruction.

Confidence: **HIGH** — pattern audit is direct on observed triples.

## §9 Feature session bucket

### §9.1 Respin (SpinType=50, ReMarks='ReSpin', CostCredits=0)

- trigger rate: **1.3154%** of paid rounds spawn a respin
- total respin rounds observed: 8,820
- respin win rate: 27.7211% of respin rounds
- respin chain length: mostly 1, rarely 2 (observed in chunk_0001 sample)

### §9.2 Mini-game (SpinType=51, ReMarks='MiniGame[N,...]')

- trigger rate: **1.0534%** of paid rounds spawn a mini-game
- total mini-game rounds observed: 6,847
- avg mini-game win: 27.1963× bet
- token distribution (top 10): `{'108': 2051, '109': 2044, '110': 1955, '102': 1376, '101': 1365, '103': 1014, '105': 970, '104': 961, '107': 792, '106': 771}`
  - tokens 100-110 appear in single or comma-separated lists (e.g. `MiniGame[108]`, `MiniGame[103,109]`) — each token likely = a prize-tier event inside the mini-game

### §9.3 Combined

- any feature triggered: **2.3572%** of paid rounds

Confidence: **HIGH** for cadence; **MED** for mini-game token-tier semantics (token-token interaction is plausible inference, not proven from rawdata alone).

## §10 Top-prize cadence cross-mode escalation — **N/A this session**

Cross-mode comparison requires mode 5 (super-lucky) and mode 2 (lucky) baselines. Mode 1 alone cannot characterize the escalation. Mode 2/5/7 ship in subsequent sessions per SESSION_BRIEF ("以后所有机台都这么做" universal workflow).

## §11 Cross-mode invariants — **N/A this session**

Universal cross-mode invariants (LUCKY-MONO, MODE7-LOCK, MODE5-BASE-LOCK, mode-pair monotonicity) require all 4 modes characterized. Mode 1-only this session.

## §12 Schema fingerprint vs production

- envelope claimed: `_upstream_schema_fingerprint = 5d02773c069fc396`
- observed (sha256[:16] of sorted keys of round 0): `5d02773c069fc396`
- **match**: YES

All 41 chunks observed at config_md5 `b99e0b0523794944f807154a0da22e5e` / code_md5 `6e02924b710ae1ba0845223730cf728e` (consistent across the entire inventory — see Stage 1a).

Confidence: **HIGH**.

---

## Cross-signal sanity (per `memory/feedback_self_verify_output.md`)

| signal | value | reference | delta |
|---|---|---|---|
| RTP from total session_win / total_bet | 93.2306% | (anchor) | 0.00 |
| RTP from sum of pay_id RTP pp (base+respin) | 64.5825% | anchor | -28.6482pp |
| RTP from mini-game wins (not in pay_id) | 28.6482% | (additive) | n/a |
| RTP pay_id_sum + minigame | 93.2306% | should == total | -0.0000pp |
| RTP from bucket sum | 93.2306% | anchor | +0.0000pp |
| Hit rate from sessions | 14.1969% | (anchor) | 0.00 |
| Hit rate from bucket sum | 14.1969% | anchor | +0.0000pp |
| total_prob sanity | 1.0000000000 | should be 1.0 | +0.0000000000 |

**Verdict**: pass.

**On the pay_id_sum gap**: mini-game rounds (SpinType=51) **do not have** a `PayoutIdToWinAmount` field — their wins come from a separate logic class (`M43WinMiniGameGenerator`) and bypass the payline analysis. The correct identity for M43 is `sum(pay_id_rtp) + minigame_rtp == total_RTP`, which holds to within 0.5pp here. The bucket RTP sum matches total RTP because the bucket aggregation is session-centric (includes mini-game wins).

---

## SpinType distribution (sanity)

```json
{
  "1": 650000
}
```

## ReMarks distribution (top 15)
```json
{
  "": 650000
}
```
