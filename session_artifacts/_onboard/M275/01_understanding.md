# M275 mode_1 — W1 Understanding (ground truth, evidence only)

> onboard-understander artifact. Cached rawdata only; deep-parsed (json.loads the JSON-string
> `roundResult` / double-loads `analysisResult`) via `fresh_slotlab.analyzer.st_inventory` +
> `parse_rounds`. NO design, NO reuse verdict — tables and counts only.

---

## 0. Provenance (FIRST)

| item | value |
|---|---|
| chunks | `rawdata/M275/mode_1/chunk_0001.json`, `chunk_0002.json` (2 chunks, only chunks in dir) |
| `_cache_version` | **3 on both** → REAL console sampler. **Zero virtual (v2/`_dev_sample`) chunks.** |
| `_config_md5` | `8c89bc953a934d8908616ed63f9fd3a4` (both chunks — **single bucket**, no mixing) |
| `_code_md5` | `9b453ffc5c1d8f120a771e88e29e14ca` (both) |
| `_saved_at` | 2026-05-20T14:57:03Z / 14:57:25Z |
| `_bet` | 1000 (both) |
| `_spin_times` × `_robot_count` | 5000 × 8 per chunk → 16 robots, 80,000 paid spins total |
| `_payload_sha256` | a5b77efd… / c3298fed… (present; load via canonical parser) |
| **md5 drift vs roster** | `configs/machines.json` current for M275 = cfg `2c98ce050b792d3563f772a58eaad1ec` / code `ebad114525bb63322afdcda7e8850e3f` → **this cache is a HISTORICAL bucket** (upstream drifted after 2026-05-20). Not a blocker for value-agnostic structure work; any served REPORT must be generated per-bucket and stamped with the chunk md5s (8c89bc95…/9b453ffc…), not the roster's current. |
| robot envelope | exactly 2 keys per robot: `roundResult` (JSON string) + `analysisResult` (JSON string of JSON strings) |
| rounds parsed | **89,090** (per-robot 5450–5720; = 80,000 ST140 + 9,090 ST126) |

---

## 1. SpinType inventory (count / share / field signature)

Only **two** SpinTypes exist in 89,090 rounds.

| ST | proposed name | count | share | rounds/robot |
|---|---|---|---|---|
| **st140** | NormalCollectionSpin (server's own feature name) | 80,000 | 89.80% | 5,000 (exactly `_spin_times`) |
| **st126** | NewFreespin (server's own feature name) | 9,090 | 10.20% | 450–720 |

Field signatures (every field below is at presence ratio **1.0** within its ST — there are no optional fields on this machine; the signature IS the core):

| field | st140 | st126 | value behavior (proven below) |
|---|---|---|---|
| SpinType | ✓ | ✓ | 140 / 126 |
| BetAmount | ✓ | ✓ | 1000 always (both STs) |
| CostCredits | ✓ | ✓ | **1000 on st140, 0 on st126** (real cost) |
| WinCredits | ✓ | ✓ | real per-round win (== sum of PayoutIdToWinAmount in **all 89,090 rounds**, 0 mismatches) |
| PayoutIdToWinAmount | ✓ | ✓ | payid → win map; ids 1–8, 666 (st140 only), 27502/3/4 |
| PayoutByPayline | ✓ | ✓ | `line:label-label(pos,pos,pos,);` per winning line |
| StopSymbolsByCol | ✓ | ✓ | 3 reels × 3 rows, `-`-joined |
| ReMarks | ✓ | ✓ | st140: always `""`; st126: `"Freespin N; "` N=1..10 |
| ReelSkin | ✓ | ✓ | st140: always 1; st126: 11/21/31 (deterministic schedule, §7.2) |
| GameplayTriggerType | ✓ | ✓ | st140: always 0; st126: **0 (scatter-opened) or 2 (collect-peak-opened)** |
| SpinTimes | ✓ | ✓ | paid-spin serial 1..5000; **st126 rounds carry the SpinTimes of their triggering paid spin** (909/909 sessions) |
| RTPId | ✓ | ✓ | always 1 |
| PayLineGroupId / PayoutGroupId | ✓ | ✓ | always 0 / 0 |
| IsLackCreditsSpin | ✓ | ✓ | always false |
| CurJackpotStoreWin | ✓ | ✓ | **always 0** (80,000 + 9,090 rounds printed/tallied — M279-style test-interface zeroed field) |
| LastCredits | ✓ | ✓ | robot wallet ~1e14, moves with net win (e.g. robot0 9.9999999999e13 → +15,000 net) |
| RewardLastNode | ✓ | ✓ | winning node labels, e.g. `["8-"]`, `["666-"]`, `["27502-"]` |
| **CollectCount** | ✓ | — | spin counter 1→1000, wraps (§6) |
| **AccCredits** | ✓ | — | = 100 × CollectCount exactly (§6) |
| **CreditsSymbols** | ✓ | — | constant string `"100:1000 | "` in all 80,000 rounds |
| **SymbolIndexToRewards** | ✓ | — | constant `"{}"` in all 80,000 rounds |
| **ExtraRatio** | — | ✓ | escalating freespin multiplier ×100 (§7.3) |

---

## 2. ST roles — justified from OWN fields

- **st140 — paid base spin with collection counter.** CostCredits=1000 every round; exactly `_spin_times` per robot; CollectCount/AccCredits tick on it; payid 666 (win=0) marks the scatter trigger; `RewardLastNode` carries `"666-"` on exactly those 829 rounds.
- **st126 — free bonus spin (reel-spin event, zero cost).** CostCredits=0, ReMarks `Freespin 1..10`, own reel skins (11/21/31) which contain **zero `bonus` symbols** (9,090/9,090 rounds have bonus-count 0 → no retrigger is structurally possible), carries `ExtraRatio` (escalating win multiplier). `win=0` rounds (6,814) are still meaningful events: they advance the deterministic skin/ER ladder.
- There is **no separate settlement/choice/state ST**: every round settles itself (`sum(payids)==WinCredits` 89,090/89,090). The collect-peak completion ("BuffCollectionMap" in the server's taxonomy) has **no ST of its own** — it exists only as a counter state on st140 + a GTT=2 freespin session + a zero-win FeatureWin row.

---

## 3. State machine (per-robot SpinType sequence)

```
st140 (paid, cc=k) ──(no signal: 78,262 of 80,000)──────────────► next st140 (cc=k+1)
st140 + payid666 (3 bonus symbols)      ─► 10 × st126 (GTT=0, FS1..FS10) ─► next st140
st140 with CollectCount==1000 (peak)    ─► 10 × st126 (GTT=2, FS1..FS10) ─► next st140 (cc=1)
st140 with BOTH signals (1 occurrence)  ─► 10 × st126 (GTT=2) ─► 10 × st126 (GTT=0) ─► next st140
```

- Every st126 block starts at `Freespin 1` (0 orphan blocks) and each `Freespin N` N=1..10 appears exactly **909** times → **909 sessions, all exactly 10 spins, zero truncated** (the last possible session, triggered on paid spin 5000, is still complete — rounds/robot > 5000).
- All 10 rounds of every session share the trigger round's `SpinTimes` (909/909) — the protocol's own session binding.
- The one double-trigger round (robot 3, SpinTimes=4000: cc=1000 AND payid 666, win=0): the **collect-peak session (GTT=2) runs first**, then the scatter session (GTT=0). Wins 32,000 + 48,500.

---

## 4. Economy — what is real, what is preview, what settles what

| claim | proof |
|---|---|
| `WinCredits` is the real win on BOTH STs | `sum(PayoutIdToWinAmount.values()) == WinCredits` in 89,090/89,090 rounds |
| payid **666 is a marker, not money** | n=829, total win 0.0 (all occurrences) |
| nothing else is a preview | no other zero-sum payid; no offer/choice fields exist |
| freespins cost nothing | CostCredits=0 on all 9,090 st126 |
| **the collection pot is NEVER paid as credits** | AccCredits peaks at 100,000 (100× bet) when cc=1000, but the 80 peak rounds pay only ordinary line wins (68 of 80 win 0; payids on them: 4×3, 8×5, 7×3, 3×2, 5×1, 666×1 — no 100,000 entry). Pot value in-data = the 10 GTT=2 freespins only |
| totals reconcile with server | our parse: st140 35,857,500 + st126 35,531,500 = **71,389,000** == server TotalWin aggregate 71,389,000 (16 robots). Cost 80,000×1000 → RTP **89.24%**, split 44.82pp base + 44.41pp freespin |

Base-game line economy (st140): hit rate **13.86%** (11,087/80,000), max single-round win 125× bet.
Freespin economy (st126): hit rate **25.04%** (2,276/9,090), max single-round win 325× bet.

---

## 5. Server `analysisResult` — the machine's OWN tier × feature taxonomy

3 views (`TotalWin` / `FeatureWin` / `SummaryWin`), 3 feature keys in all 16 robots:
**NormalCollectionSpin**, **NewFreespin**, **BuffCollectionMap**. Tier keys observed:
`-1` (win=0), `0` ((0,1)×), `1`, `5`, `10`, `20`, `50`, `100`, `300` — tier = largest threshold ≤ win/bet.

Aggregated over all 16 robots, with our reconciliation:

### 5.1 TotalWin — unit = paid spin, value = paid spin win + its session(s) win (session-centric)

| tier | Times | WinCredits | our recomputation |
|---|---|---|---|
| -1 | 68,107 | 0 | 68,107 / 0 ✓ |
| 0 | 2,346 | 1,173,000 | ✓ exact |
| 1 | 6,577 | 11,325,500 | ✓ exact |
| 5 | 1,453 | 8,057,500 | ✓ exact |
| 10 | 676 | 8,399,500 | ✓ exact |
| 20 | 533 | 16,513,500 | ✓ exact |
| 50 | 226 | 14,966,000 | ✓ exact |
| 100 | 81 | 10,616,000 | ✓ exact once tier-300 split out |
| 300 | 1 | 338,000 | ✓ (the 338× paid round = best session) |
| Σ | **80,000** | **71,389,000** | ✓ |

### 5.2 FeatureWin — unit = round of that feature

| feature | Σ Times | Σ Win | == our parse |
|---|---|---|---|
| NormalCollectionSpin | 80,000 | 35,857,500 | == st140 per-round, tier-exact (−1:68,913 / 0:2,350 / 1:6,580 / 5:1,369 / 10:517 / 20:206 / 50:48 / 100:17) |
| NewFreespin | 9,090 | 35,531,500 | == st126 per-round, tier-exact (−1:6,814 / 0:22 / 1:576 / 5:592 / 10:549 / 20:400 / 50:111 / 100:25 / 300:1) |
| BuffCollectionMap | **80** | **0** | == the 80 collect-peak events; carries zero win of its own |

### 5.3 SummaryWin — unit = feature SESSION

- NormalCollectionSpin: identical to its FeatureWin (a paid round is its own session).
- BuffCollectionMap: 80 × tier −1, win 0.
- NewFreespin (session totals): Σ Times = **908**, Σ Win = 35,531,500:

| tier | server Times | our 909-session Times | server Win | our Win |
|---|---|---|---|---|
| -1 | 43 | 43 | 0 | 0 |
| 0 | 1 | 1 | 500 | 500 |
| 1 | 47 | 47 | 125,000 | 125,000 |
| 5 | 89 | 89 | 619,000 | 619,000 |
| 10 | 160 | 160 | 2,259,000 | 2,259,000 |
| 20 | **326** | **328** | 10,996,000 | 11,076,500 |
| 50 | **177** | **176** | 12,332,000 | 12,251,500 |
| 100 | 64 | 64 (65 before 300-split) | 8,862,000 | 8,862,000 |
| 300 | 1 | 1 | 338,000 | 338,000 |

The single 908-vs-909 discrepancy is fully explained by the double-trigger round: the server's
SummaryWin **merges the back-to-back pair into ONE session** (32,000 + 48,500 = 80,500 → one tier-50
entry) while we count two tier-20 sessions; the win deltas (−80,500 @20 / +80,500 @50) match exactly.

---

## 6. CollectCount mechanic (the counter, per the data)

| property | evidence |
|---|---|
| tick | **+1 on every paid spin**, unconditionally: all 79,936 in-robot transitions are (k → k+1); each value 1..1000 appears exactly 80 times (16 robots × 5 cycles) |
| peak | **1000** |
| at peak | a 10-spin st126 session with **GTT=2** follows immediately (80/80), then counter resets: transition (1000 → 1) observed 64 times (16 robots × 4 in-sequence wraps; the 5th peak is each robot's last paid spin) |
| pot | `AccCredits == 100 × CollectCount` exactly (every value 100..100,000 appears 80 times); `CreditsSymbols` is the constant `"100:1000 | "` in all 80,000 rounds (reads as collect-value 100 per bet 1000 — a config echo, not a per-round landing record) |
| pot settlement | **never paid as WinCredits** (§4) |
| determinism | with 5000 paid spins per robot the peak lands on SpinTimes 1000/2000/3000/4000/5000 — confirmed: GTT=2 trigger rounds have exactly those SpinTimes values |

So in THIS test interface the collection is a deterministic 1-in-1000-paid-spins pity timer.

---

## 7. SESSION STRUCTURE — opening-signal partition (exhaustive proof)

909 sessions reconstructed (block split on `Freespin 1`; trigger = immediately preceding st140).

### 7.1 Opening signals observed on the trigger round

| signal on preceding paid round | sessions | session GTT | session win total | proof of exhaustiveness |
|---|---|---|---|---|
| `payid 666` (== 3 bonus symbols, §8.2) , cc<1000 | 828 | all 0 | 32,637,000 | every one of the 829 payid-666 rounds is followed by st126 (829/829) |
| `CollectCount == 1000`, no 666 | 79 | all 2 | 2,814,000 | every one of the 80 cc=1000 rounds is followed by st126 (80/80) |
| BOTH on one round (1 round: robot 3, SpinTimes 4000) | 2 (GTT=2 first, then GTT=0) | 2, then 0 | 32,000 + 48,500 | the signals are ADDITIVE — both sessions granted |
| no signal (orphan) | **0** | — | — | 909 = 829(666) + 80(cc-peak); no block lacks a signal |

- **Disjoint + exhaustive:** 829 + 80 = 909; zero double-attribution (the both-case is two distinct sessions from two distinct signals, separable by GTT); totals reconcile: 32,637,000 + 2,814,000 + 80,500 = **35,531,500** = st126 total = server NewFreespin total.
- **GTT is a perfect path discriminator**: scatter-opened sessions are GTT=0 on all 10 rounds; peak-opened GTT=2 on all 10 (no mixed session).
- **Cross-check vs prior ground truth** (`session_artifacts/_arch_playtype/02_traces.md`, M275 section, older 5-chunk cache: 437 scatter / 39 BCM / 1 both / 0 orphans): independently re-derived here with identical STRUCTURE — same two signals (`pay_id 666`; `CollectCount==peak 1000`), same disjointness (1 rare both-case), same exhaustiveness/reconciliation. Absolute counts differ as expected (different cache size). NEW beyond the prior trace: the GTT 0/2 discriminator, the both-case ordering (peak session first), and the server-side SummaryWin merge of the both-pair.

### 7.2 Do the two paths have different configs? (side-by-side)

| dimension | scatter666 (829 incl. both-pair GTT0) | ccpeak (80 incl. both-pair GTT2) |
|---|---|---|
| trigger rate per paid spin | 829/80,000 = **1.036%** (random) | 80/80,000 = **0.100%** (deterministic 1/1000) |
| spins granted | 10 (always) | 10 (always) |
| Freespin numbering | 1..10 | 1..10 |
| reel-skin schedule | FS1-3 skin 11, FS4-7 skin 21, FS8-10 skin 31 | identical |
| ER@FS1 dist | 100:606, 200:130, 300:69, 500:23 (n=828) [+both: 100] | 100:53, 200:13, 300:8, 500:5 (n=79) [+both: 100] |
| ER step dist | +100:57.2% +200:26.6% +300:12.2% +500:4.0% | +100:59.4% +200:26.8% +300:11.1% +500:2.6% |
| ER@FS10 mean | 1645 (max 2800) | 1596 (max 2400) |
| session win mean | 39.4× bet (median 28.5×, max 338×) | 35.6× bet (median 30.0×, max 172.5×) |
| zero-win sessions | 39/828 = 4.7% | 4/79 = 5.1% |
| session tier dist (−1/0/1/5/10/20/50/100/300) | 39/1/42/81/150/291/164/60/1 | 4/0/5/8/10/37/12/4/0 |
| RTP contribution | **40.86pp** | **3.56pp** |

→ Within sampling noise of n=80, the two paths run the SAME session config (same length, skins,
ER mechanics); the data shows **no per-path config difference except the trigger itself and the
attribution (GTT)**. What differs is frequency (10×) and hence RTP share (40.86 vs 3.56pp).

### 7.3 ExtraRatio (the escalating freespin multiplier)

- FS1 starts at ER ∈ {100, 200, 300, 500} (72.7/15.7/8.5/3.1%); **every** subsequent spin adds
  ∈ {+100, +200, +300, +500} (8,181/8,181 steps positive; 0 flat, 0 decreasing).
- Marginal ER range observed: 100 → 2800 (28×).
- **Win law (proven exactly, 0 violations):** line win = base payout × (ER/100) × (wildNx if the
  multiplier wild sits ON the line). Tests: 1,280 single-line no-wildNx rounds all == base×ER/100;
  266 single-line wildNx rounds all ∈ {base×ER/100 (wild off-line, 46), base×N×ER/100 (220)};
  all 2,905 st126 base-payid entries divisible by base×ER/100.
- The fixed specials (27502/3/4) are **NOT multiplied by ER** (46 st126 occurrences, all at fixed
  100,000/25,000/10,000).

---

## 8. CROSS-DIMENSIONS (every cross the data supports, real numbers)

### 8.1 st140 payid × occurrence rate × RTP (base paytable derived from single-line no-wildNx rounds)

| payid | base win (× bet) | st140 n (rate/paid) | st140 RTP pp | st126 n | st126 RTP pp |
|---|---|---|---|---|---|
| 1 | 5.0 | 1,025 (1.281%) | 11.84 | 282 | 12.78 |
| 2 | 3.0 | 1,225 (1.531%) | 7.26 | 245 | 6.95 |
| 3 | 2.5 | 457 (0.571%) | 2.52 | 153 | 3.37 |
| 4 | 1.0 | 3,464 (4.330%) | 6.40 | 837 | 7.80 |
| 5 | 2.0 | 579 (0.724%) | 2.59 | 146 | 2.63 |
| 6 | 1.5 | 737 (0.921%) | 2.56 | 193 | 2.79 |
| 7 | 1.0 | 1,834 (2.292%) | 4.21 | 339 | 3.37 |
| 8 | 0.5 | 3,513 (4.391%) | 3.37 | 710 | 3.35 |
| 666 | 0 (trigger) | 829 (1.036%) | 0 | — | — |
| 27502 | 100 fixed | 17 (0.021%) | 2.13 | 6 | 0.75 |
| 27503 | 25 fixed | 14 (0.017%) | 0.44 | 8 | 0.25 |
| 27504 | 10 fixed | 122 (0.152%) | 1.53 | 32 | 0.40 |

(1,949 st140 / 675 st126 rounds carry >1 payid; sum always == WinCredits.)

### 8.2 Trigger-context × outcome: bonus-symbol count on st140 (near-miss dimension)

| bonus symbols on grid | rounds | share | has payid 666 |
|---|---|---|---|
| 0 | 37,906 | 47.4% | never |
| 1 | 32,140 | 40.2% | never |
| 2 | 9,125 | **11.4% (near-miss)** | never |
| 3 | 829 | 1.04% | **always** (829/829) |

Max one bonus per reel (per-reel max = 1 in all 80,000 rounds) → trigger = bonus on all 3 reels.
`RewardLastNode` contains `"666-"` on exactly those 829 rounds.

### 8.3 Symbol (RewardLastNode/payline label) × multiplier wild — all-wild lines = the specials

For every all-wild line in 89,090 rounds (geometry from §8.6), keyed by the reel-2 wild type:

| reel-2 wild on the all-wild line | payid produced | fixed win | n |
|---|---|---|---|
| wild | 27504 | 10× | 154 |
| wild2x | 27503 | 25× | 22 |
| wild5x | 27502 | 100× | 23 |
| wild10x | — | — | **0 observed in 89,090 rounds** (value not determinable from this sample) |

wildNx on a NORMAL symbol line multiplies the line: verified on st140 single-line rounds, e.g.
payid 1: 5,000 base → 10,000 (wild2x) / 25,000 (wild5x) / 50,000 (wild10x); specials immune
(27502 stays 100,000 even with wild5x on grid).

### 8.4 Reel-skin × symbol vocabulary (3 reels × 3 rows; from all StopSymbolsByCol)

| skin (where used) | reel-1 top symbols | reel-2 | reel-3 | bonus present | wildNx present |
|---|---|---|---|---|---|
| 1 (st140) | blank 47.5%, high7, 1bar, mid7, 2bar, bonus, wild, low7, 3bar | blank, wild, 1bar, mid7, bonus, …, wild5x 2.1%, wild10x 1.1%, wild2x 1.0% | blank, bonus, 1bar, mid7, 3bar, … | yes (all 3 reels) | 2x/5x/10x on reel 2 |
| 11 (FS1-3) | blank 41.7%, 1bar, high7, 2bar, mid7, wild, 3bar, low7 | blank, wild 19%, …, wild5x 2.1%, wild2x 1.9%, wild10x 1.8% | blank, low7, 1bar, 2bar, 3bar, wild, high7, mid7 | **no** | 2x/5x/10x on reel 2 |
| 21 (FS4-7) | blank 46.6%, 1bar, high7, 2bar, wild, mid7 | blank, 1bar, mid7, low7, wild, **wild2x only** 6.8% | blank 59.7%, wild, mid7, high7, … | **no** | 2x only, reel 2 |
| 31 (FS8-10) | blank 38.7%, 1bar, high7, wild, 2bar, mid7 | blank, mid7, 1bar, wild, low7 | blank 64.9%, rest ~5% each | **no** | **none** |

Wild counts per round: st140 0/1/2/3 = 34,111/36,306/8,966/617; st126 = 3,298/4,050/1,549/193.

### 8.5 Freespin index × skin × ER × outcome (the in-session arc)

| FS index | skin | hit rate | mean win (× bet) | max (× bet) | ER mean |
|---|---|---|---|---|---|
| 1 | 11 | 43.8% | 2.91 | 150 | 145 |
| 2 | 11 | 38.8% | 4.76 | 160 | 291 |
| 3 | 11 | 40.7% | 7.04 | **325** | 438 |
| 4 | 21 | 28.9% | 3.45 | 84.5 | 605 |
| 5 | 21 | 26.1% | 4.28 | 94.5 | 769 |
| 6 | 21 | 28.3% | 6.08 | 136.5 | 936 |
| 7 | 21 | 29.8% | 7.32 | 105 | 1,103 |
| 8 | 31 | 5.8% | 1.19 | 90 | 1,285 |
| 9 | 31 | 4.4% | 0.89 | 75 | 1,461 |
| 10 | 31 | 3.7% | 1.17 | 110 | 1,641 |

Per-skin rollup: skin 11 hit 41.1% / mean 4.90×; skin 21 hit 28.3% / 5.28×; skin 31 hit **4.7%** / 1.08×
— the reels get colder exactly as the multiplier ladder climbs (rare-but-huge tail design, visible in data).

### 8.6 Payline geometry (decoded from PayoutByPayline positions)

5 paylines on the 3×3 grid: line 1 = middle row (100,200,300), 2 = top (99,199,299), 3 = bottom
(101,201,301), 4 = diagonal TL→BR (99,200,301), 5 = diagonal BL→TR (101,200,299).
Line usage counts (all winning lines): 1: 2,975 / 2: 4,206 / 3: 3,738 / 4: 3,041 / 5: 2,943.

### 8.7 ER-step independence checks

- **vs wilds on previous or current spin:** step dist ≈ unchanged with/without wildNx (e.g. +100 share
  57.2% no-wildNx vs 55.7% with wild2x-prev) → not wild-driven.
- **vs previous step (autocorrelation):** next-step dist flat across prev ∈ {100,200,300,500} (+100 share
  55–60%) → memoryless.
- **vs FS index (NOT flat):** FS1→2/FS2→3 (skin 11): +100 ≈ 71%; skin-21 steps: +100 ≈ 54–56%;
  FS7→8..FS9→10: +100 ≈ 50–53% with +500 rising to 6.1–7.5% → the step weighting varies by
  session segment/skin.

---

## 9. Could NOT determine / testspin-blind (honest gaps)

1. **ER step driver:** the in-engine weighting behind FS1-start {100,200,300,500} and the per-spin
   step draw is not observable; proven independent of visible wilds and of the previous step, and
   segment-dependent (§8.7) — but only the marginals are recoverable from rawdata.
2. **wild10x all-wild line:** zero occurrences in 89,090 rounds — its special payid/prize is
   unknowable from this sample.
3. **Collection in production:** here CollectCount ticks +1 on EVERY paid spin and `CreditsSymbols`
   is a constant `"100:1000 | "` — whether the production game ties ticks to actual credit-symbol
   landings (and pays the AccCredits pot) cannot be determined; in THIS interface the pot is never
   settled as WinCredits (§4) and `SymbolIndexToRewards` is always `"{}"`.
4. **CurJackpotStoreWin always 0** (all 89,090 rounds printed/tallied) — M279-pattern test-interface
   zeroed field; any real jackpot store is out-of-engine for testspin. Parse-as-is, forward-compatible.
5. **Single-valued fields** RTPId=1, PayLineGroupId=0, PayoutGroupId=0, IsLackCreditsSpin=false,
   GameplayTriggerType=0-on-st140: semantics beyond "constant in this bucket" not determinable.
6. **GTT vocabulary:** only values 0 and 2 appear; whether other values exist (e.g. 1) on other
   modes/configs is unknown from this mode.
7. **md5-drift deltas:** the roster's current config 2c98ce05… may have retuned any of the numbers
   above (RTP 89.24%, trigger rates, paytable); structure claims are value-agnostic but every NUMBER
   in this artifact belongs to bucket 8c89bc95…/9b453ffc… only.
8. **Player-state continuity:** robots are fresh wallets; CollectCount always starts a robot at 1 —
   carry-over behavior of a real player's mid-cycle counter across sessions is out of testspin's scope.
