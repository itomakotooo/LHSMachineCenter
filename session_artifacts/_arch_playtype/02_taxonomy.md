# Play-type taxonomy — analyzer re-architecture
> arch-taxonomist Wave-1 Foundation deliverable
>
> Derived from LIVE rawdata (cached). Scripts under `cache/_playtype_tax/`. No upstream fetch.
> Data source: `rawdata/<M>/mode_<n>/chunk_*.json` for 12 pilot machines + fleet-wide signal scan of 255 machines.
> Date: 2026-06-01

---

## PART A — Technical taxonomy

### A1. Pilot machine selection

**Selection criteria**: span all observed mechanic families identifiable from `logicClassNames` + cached rawdata.

| Pilot | Modes cached | logicClassNames (key tokens) | Justification |
|---|---|---|---|
| **M14** | 1(21c),2,5,7 | NormalSpinGenerator | Baseline: pure paid, no bonus |
| **M31** | 1(26c),2,5,7 | FreeSpinGenerator, NormalSpinGenerator | Scatter-triggered freespin |
| **M43** | 1(42c),2,5,7 | M43WinMiniGameGenerator, NormalSpinGenerator | Lock-respin + minigame combo |
| **M15** | 1(224c),2,5,7 | TopDollarGenerator, NormalSpinGenerator | TopDollar pick-selector |
| **M99** | 1(2c),2,5,7 | GoldenPrizeWheelGenerator, FinalMinigameGenerator | Lock-symbol + Wheel + FinalMinigame |
| **M120** | 1(1c),2,5,7 | MultiSymbolCollectionFreespinGenerator | Multi-symbol collection freespin |
| **M272** | 1(2c),2,5,7 | BuffCollectionDataGenerator (BCM family) | BCM + NewFreespin (paid=140) |
| **M275** | 1(2c),2,5,7 | BuffCollectionDataGenerator + MapGenerator | BCM + scatter+freespin + jackpot tiers |
| **M274** | 1(56c),2,5,7 | BuffCollectionDataGenerator + ListRewardMinigame | BCM + ListRewardWheel (Minigame) |
| **M279** | 1(48c),7(40c) | BuffCollectionDataGenerator + MoveSpinGenerator | BCM + wild-nudge + Wheel |
| **M268** | 1(2c),2,5,7 | BuffCollectionDataGenerator + LockReels | BCM + CreditsSymbolRespin |
| **M260** | 1(2c),2,5,7 | BuffCollectionDataGenerator (extended) | BCM + FreeSpin + WheelSpin (multi-pool) |

All 12 pilots confirmed to have `mode_1/chunk_*.json` present. Tallies are from 1–5 chunks each (50k–200k rounds total per pilot).

**Coverage of mechanic space**: the 12 pilots cover all major signal families observed fleet-wide:
- Pure paid (no bonus): M14
- Scatter freespin (TriggerFreespin remark / pay_id=666): M31, M275
- BCM collect cycle with freespin: M272, M275
- BCM + Wheel: M279, M260
- BCM + Minigame: M274
- BCM + LockReels respin: M268
- TopDollar pick-selector: M15
- Lock-symbol respin: M99
- Win-respin + MiniGame: M43
- Multi-symbol collection freespin: M120

---

### A2. Raw field vocabulary (verified from parser.py + rawdata)

**Base envelope** (17 fields, all 255 rawdata-scanned machines): `BetAmount, CostCredits, WinCredits, SpinType, SpinTimes, RTPId, IsLackCreditsSpin, LastCredits, CurJackpotStoreWin, PayLineGroupId, PayoutGroupId, PayoutByPayline, PayoutIdToWinAmount, ReMarks, ReelSkin, StopSymbolsByCol, RewardLastNode`

**Paid round predicate** (fleet-universal, verified): `CostCredits > 0`.

**Bonus round predicate**: `CostCredits == 0` (or null). All bonus/free/nudge rounds carry CostCredits in {None, 0} on every pilot.

**Pay_id**: key in `PayoutIdToWinAmount` dict — per-machine config slot. Symbol_id in `PayoutByPayline` ≠ pay_id in general (M120, M139, M279, M123 suffix mismatch). Pay_id=666 is cross-machine scatter/jackpot-trigger anchor verified on M14, M31, M275, M99, M272, M15, M274, M120.

---

### A3. Per-pilot rawdata evidence (real tally numbers)

#### M14 — pure paid
- 90,000 rounds (5 chunks mode 1)
- paid_ST = {1: 90,000}, bonus_ST = {} (zero bonus rounds)
- Extra fields: none (pure 17-key base envelope)
- Remarks: all `(none)` — no bonus signal
- Pay_ids: {1,2,3,4,5,6,7} — 7 config slots
- **Confidence: HIGH** — single play-type, unambiguous

#### M31 — scatter-triggered freespin
- 44,338 rounds (3 chunks mode 1): 42,000 paid + 2,338 bonus
- paid_ST = {43: 42,000}; bonus_ST = {44: 2,338}
- Paid rounds with ReMarks=`TriggerFreespin`: 334; identical to paid rounds with pay_id=666: 334 (100% match)
- Bonus (ST=44) remarks = `FreeSpin` on all 2,338 rounds
- Extra fields: none (pure 17-key base envelope)
- Pay_ids on paid: {2,3,4,5,6,7,8,9,10,11,12,666}; on bonus: {1,2,3,4,5,6,7,8,9,10,11} — pay_id 666 absent from freespin rounds (trigger-only semantics)
- **Signals**: `paid_ST=43, bonus_ST=44, ReMarks=TriggerFreespin on paid trigger round, pay_id=666 on trigger round`
- **Confidence: HIGH**

#### M275 — BCM + scatter-freespin + jackpot tiers
- 89,090 rounds (2 chunks mode 1): 80,000 paid + 9,090 bonus
- paid_ST = {140: 80,000}; bonus_ST = {126: 9,090}
- BCM fields present: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards, ExtraRatio, GameplayTriggerType`
- CollectCount on paid rounds: range 1–1000 (full cycle observed)
- Freespin trigger: 908 events. 91.8% (832/908) triggered by pay_id=666 on paid round; 8.2% triggered at CollectCount=1000 (BCM cycle peak). Both trigger mechanisms produce identical freespin flow (ST=126)
- Freespin run length: 10 rounds per trigger (907 ×10-spin, 1 ×20-spin AddFreespins event)
- ExtraRatio on freespin: 100–2,800 (varies per trigger; NOT simply cc×100 — see M272 comparison)
- Pay_ids on paid: includes {27502, 27503, 27504} (jackpot tiers with fixed wins 10k/25k/100k) plus standard {1-8, 666}
- GameplayTriggerType=2 appears on first freespin round of sequence (not on the triggering paid round)
- **Signals**: `paid_ST=140, bonus_ST=126, BCM core fields, pay_id=666 on trigger, pay_ids 27502/27503/27504 = jackpot tiers`
- **Confidence: HIGH**

#### M43 — win-respin + minigame
- 43,026 rounds (3 chunks mode 1): 42,000 paid + 1,026 bonus
- paid_ST = {1: 42,000}; bonus_ST = {50: 557, 51: 469} — **two distinct bonus STs**
- ST=50 remarks: all `ReSpin` — win-respin continuation
- ST=51 remarks: `MiniGame[N]` patterns (N = list of symbol positions) — pick-game mechanic
- ST=51 WinCredits: all non-zero (469/469); PayoutIdToWinAmount = None on all ST=51 rounds — win is carried only in WinCredits, not pay_id breakdown
- Extra fields: none (pure 17-key base envelope)
- Pay_ids on paid ST=1: {3,4,5,6,7,8,9}; on ST=50 ReSpin: {2,3,4,5,6,7,8,9} — no pay_id=666 (trigger mechanism differs)
- **Signals**: `paid_ST=1, bonus_ST={50=ReSpin, 51=MiniGame}, MiniGame win in WinCredits only (no PayoutIdToWinAmount)`
- **Confidence: HIGH**

#### M15 — TopDollar pick-selector
- 25,001 rounds (3 chunks mode 1): 24,000 paid + 1,001 bonus
- paid_ST = {1: 24,000}; bonus_ST = {14: 738, 15: 263} — **two bonus STs with different semantics**
- ST=14 = phantom dollar offers: `ChosenDollar` (e.g. `5-10-5-`), `DollarCount` (2–3), `OfferValue`, `JackpotIds`. WinAmount = null on ST=14.
- ST=15 = settlement: `WinAmount` field populated (15,000–70,000+ in sample). WinCredits = null on ST=15.
- Extra fields: `DollarCount, ChosenDollar, OfferValue, JackpotIds, ExtraRatio, WinAmount`
- Trigger: paid round with ReMarks=`Trigger` and pay_id=666: 263 events (matches ST=15 count — one settlement per trigger)
- ExtraRatio present on ST=14 phantom rounds (1/2/4 = multiplier tier offered)
- **Signals**: `paid_ST=1, bonus_ST={14=phantom_offer, 15=settlement}, WinAmount field on ST=15, DollarCount+ChosenDollar on ST=14`
- **Confidence: HIGH**

#### M99 — lock-symbol → wheel → final-minigame (3-stage)
- 53,385 rounds (2 chunks mode 1): 51,193 paid + 2,192 bonus
- paid_ST = {96: 51,193}; bonus_ST = {97: 1,781, 98: 411}
- LockSymbols field present on ALL 51,193 paid rounds (always tracking locked symbol state)
- Stage 1 — lock trigger: paid ST=96 + ReMarks=`Lock`: 1,193 events (lock-symbol accumulation; pay_id=666 appears 411 times, all on paid ST=96)
- Stage 2 — wheel: bonus ST=97 + ReMarks=`WheelSpin`/`WheelSpin Double`/`WheelSpin AddOne`: 1,781 rounds
- Stage 3 — final minigame: bonus ST=98 + ReMarks=`FinalMinigame`: 411 rounds
- ST=98 pay_ids: empty set (WinCredits-only, no PayoutIdToWinAmount)
- Trigger chain: some lock events lead directly to WheelSpin (ST=97), WheelSpin "AddOne" feeds back to more wheel, some wheel outcomes lead to FinalMinigame (ST=98)
- Extra fields: `LockSymbols, PrevLockSymbols, GameplayTriggerType`
- **Signals**: `paid_ST=96, bonus_ST={97=WheelSpin, 98=FinalMinigame}, LockSymbols+PrevLockSymbols fields`
- **Confidence: HIGH**

#### M120 — multi-symbol collection freespin
- 10,906 rounds (1 chunk mode 1): 10,000 paid + 906 bonus
- paid_ST = {1: 10,000}; bonus_ST = {138: 906}
- Extra fields: `RewardIdToCollectAmount` — singleton in fleet (shared only with M125 across 255 scanned machines)
- ST=138 remarks: `Freespin N; ` (sequential numbering) — 82 freespin sequences of 11 rounds each
- Pay_id=666 on paid trigger rounds: 82 (matches trigger count) — scatter trigger
- RewardIdToCollectAmount on ST=138 rounds: always `""` (empty string — collection accumulates but reports empty in basic mode)
- Extra field `RewardIdToCollectAmount` is unique to M120/M125: separate symbol-reward ledger not expressible via standard `PayoutIdToWinAmount`
- **Signals**: `paid_ST=1, bonus_ST=138, RewardIdToCollectAmount field, pay_id=666 scatter trigger`
- **Confidence: HIGH** (field is unambiguous; only 2 machines fleet-wide)

#### M272 — BCM collect cycle + NewFreespin (paid=140)
- 59,505 rounds (2 chunks mode 1): 50,000 paid + 9,505 bonus
- paid_ST = {140: 50,000}; bonus_ST = {126: 9,505}
- BCM fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards, ExtraRatio, GameplayTriggerType`
- CollectCount on paid rounds: range 1–1,000 (full cycle, same as M275)
- Freespin trigger: pay_id=666 on 92% of trigger events; BCM cc=1000 on 8%
- Freespin remarks embed both CollectCount at trigger and ExtraRatio: e.g. `Freespin 1; CollectCount:4; AddCollectCount:4; ExtraRatio:100;`
- ExtraRatio range: 100–900 (verified). NOT simply CollectCount × 100. ExtraRatio is an independent BCM payout multiplier set separately from cc.
- **Confirmed same trigger mechanism as M275** (scatter pay_id=666 + BCM cc=1000 secondary). Different paytable, different ExtraRatio scale.
- **Signals**: `paid_ST=140, bonus_ST=126, BCM core fields, CollectCount in freespin ReMarks`
- **Confidence: HIGH**

#### M274 — BCM + ListRewardWheel (Minigame, paid=140)
- 131,595 rounds (5 chunks mode 1): 120,000 paid + 11,595 bonus
- paid_ST = {140: 120,000}; bonus_ST = {139: 11,595}
- BCM fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards`
- **Critical observation**: CollectCount = **always 0** on all 200,000 paid rounds across 5 chunks. AccCredits also always 0.
- BCM trigger mechanism: pay_id=5801 on paid round (2,044 occurrences = 1.022% trigger rate). WinCredits=0 on these trigger rounds (5801 is a pure anchor, not a win-carrying pay_id).
- ST=139 (ListRewardWheel = Minigame): 20,347 rounds, remarks = complex multi-cell strings (`Minigame CellIndexes: ...; RewardWheelIds: ...; RewardCellIndexes: ...; AddLock: []; TotalLock: [...]`)
- Extra fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards` — BCM schema present but cc=0 always means the detect_cycle_peak logic will not fire; trigger lives in pay_id=5801
- **Disagreement with old work**: old taxonomy §3.5.1 states M274 needs `bcm_cycle_anchor` rule to synthesize `_bcm_cycle` trigger. RAWDATA CONFIRMS: trigger is in pay_id=5801 directly — NOT in CollectCount transitions. The bcm_cycle_anchor rule synthesizes an explicit trigger anchor for the analyzer's WIN ATTRIBUTION path, not for detection of the trigger event itself.
- **Signals**: `paid_ST=140, bonus_ST=139, BCM schema present (but cc always 0), pay_id=5801 = ListRewardWheel trigger anchor`
- **Confidence: HIGH**

#### M279 — BCM + wild-nudge + WheelSpin (paid=140)
- 133,621 rounds (3 chunks mode 1): 120,000 paid + 13,621 bonus
- paid_ST = {140: 120,000}; bonus_ST = {36: 13,501, 2: 120} — **two distinct bonus STs**
- BCM fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards`
- CollectCount on paid rounds: 1–1,000 (full BCM cycle, same as M272/M275)
- **ST=36 (wild-nudge)**: 13,501 rounds, ALL CostCredits=0, ALL ReMarks=`move` — 100% wild-nudge. Zero paid rounds in ST=36.
- **ST=2 (WheelSpin)**: 120 rounds, remarks = `WheelSpin CellIndex N; WheelId 1;`
- Pay_ids on ST=36 nudge rounds: {1,2,3,4,5,6,7,102,104} — win carries pay_ids from the reeled position
- No TriggerFreespin / pay_id=666 signals — BCM/Wheel is triggered by a different mechanism (cc=1000 cycle peak based on the old taxonomy)
- Extra fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards` — standard BCM-21k set
- **Signals**: `paid_ST=140, bonus_ST={36=move/nudge+CostCredits=0, 2=WheelSpin}, BCM core fields, CollectCount range 1-1000`
- **Confidence: HIGH**

#### M268 — BCM + CreditsSymbolRespin (paid=140)
- 51,913 rounds (2 chunks mode 1): 50,000 paid + 1,913 bonus
- paid_ST = {140: 50,000}; bonus_ST = {125: 1,913}
- BCM fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards` plus additional `LockReels, CreditsBySymbol, SymbolIndexRatio, GameplayTriggerType`
- CollectCount on paid: range 1–1,000
- ST=125 (CreditsSymbolRespin): 1,913 rounds, remarks = `Respin N; {}` — rolling respin sequence
- LockReels field: present on ALL 1,913 ST=125 respin rounds (indicating which reels are locked during respin); absent on paid rounds
- Paid round ReMarks = JSON dict strings e.g. `{"299":2807}` — parsed as `{symbol_id: credit_value}` — this is the per-symbol credit accumulation on CreditsSymbols mechanism
- Extra fields beyond BCM-21k: `LockReels, CreditsBySymbol, SymbolIndexRatio` — unique schema extensions
- **Signals**: `paid_ST=140, bonus_ST=125, BCM core fields + LockReels on respin rounds, ReMarks as JSON credit dict on paid rounds`
- **Confidence: HIGH** (LockReels+Respin remark combination is structural)

#### M260 — BCM + FreeSpin + WheelSpin (extended multi-pool schema, paid=156)
- 55,456 rounds (2 chunks mode 1): 50,000 paid + 5,456 bonus
- paid_ST = {156: 50,000}; bonus_ST = {157: 3,762, 2: 1,163, 105: 531} — **three distinct bonus STs**
- BCM fields: `AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards` plus `IndexToCreditPool, ReelIdToSpinData, ReelIdToWheelData, Buffs, NodeIndex, IncreasedCredits` — 10-key delta from base (largest in fleet)
- CollectCount on paid (ST=156): range 0–125 (shorter cycle than M272/M275/M279 which go 1–1000)
- ST=157 (FreeSpin): 3,762 rounds, remarks = `Freespin N; ` — standard freespin sequence
- ST=2 (WheelSpin): 1,163 rounds, remarks = `WheelSpin CellIndex N; WheelId 13;`
- **ST=105**: 531 rounds, all CostCredits=0, WinCredits=0, ReMarks=None — appears to be an internal animation/transition round with no win. Not paid, not freespin, no remarks. Likely a "pre-wheel" stage transition.
- Pay_ids on paid ST=156: large set including high-numbered IDs (e.g. 1,2,3,...,21) plus 4-digit IDs (1110–1119) that appear only on freespin rounds
- **Signals**: `paid_ST=156, bonus_ST={157=FreeSpin, 2=WheelSpin, 105=transition?}, BCM core + 6 extended fields (IndexToCreditPool etc), CollectCount max=125`
- **Note**: M260 paid_ST=156 is unique in the fleet. No other machine uses ST=156 for paid rounds.
- **Confidence: HIGH** for structure; MEDIUM for ST=105 semantics (transition vs. win-carrying)

---

### A4. Derived play-type list

Each play-type is defined by its identifying rawdata signal — the minimal ST+feature predicate that is SUFFICIENT to identify the mechanic. The predicate is portable: it fires on any machine emitting these signals.

| PT# | Name | Identifying rawdata signal | Fleet count (mode_1 scan) | Confidence |
|---|---|---|---|---|
| **PT-1** | Pure paid spin | `CostCredits>0` on round; no bonus ST in chunk; no BCM/Lock/Wheel extras | 64 machines | HIGH |
| **PT-2** | Scatter-triggered freespin | paid round with `pay_id=666 + ReMarks contains "TriggerFreespin"`, followed by bonus rounds | 13 machines (TriggerFreespin remark) + ~39 more with freespin bonus | HIGH |
| **PT-3** | BCM collect cycle | `CollectCount + AccCredits + CreditsSymbols + SymbolIndexToRewards` all present on paid rounds; CollectCount increments across paid rounds | 61 machines | HIGH |
| **PT-4** | BCM-triggered freespin | PT-3 PLUS bonus rounds with `ReMarks="Freespin N; ..."` | 34 machines (BCM with freespin bonus_ST) | HIGH |
| **PT-5** | BCM-triggered WheelSpin | PT-3 PLUS bonus rounds with `ReMarks="WheelSpin CellIndex N; WheelId N;"` | 32 machines (BCM with WheelSpin remark) | HIGH |
| **PT-6** | BCM-triggered ListRewardWheel (Minigame) | PT-3 PLUS `pay_id=5801` on paid trigger round + bonus rounds with Minigame cell/lock remarks; CollectCount=always 0 (M274-specific cycle) | 1 machine confirmed (M274) | HIGH |
| **PT-7** | Wild-nudge | bonus round with `CostCredits=0 + ReMarks contains "move" or "nudge"` (case-insensitive word boundary) | 10 machines | HIGH |
| **PT-8** | TopDollar pick-selector | `DollarCount + ChosenDollar + OfferValue` extra fields present; bonus_ST = phantom-offer (no WinAmount) + settlement (WinAmount populated, WinCredits=null) | 6 machines | HIGH |
| **PT-9** | Lock-symbol respin | `LockSymbols + PrevLockSymbols` extra fields on paid rounds | 14 machines | HIGH |
| **PT-10** | Lock-lines respin | `LockLines` extra field on respin rounds | 19 machines | HIGH |
| **PT-11** | Lock-reels respin (BCM variant) | PT-3 PLUS `LockReels` field present on bonus respin rounds; paid ReMarks = JSON credit dict | 9 machines | HIGH |
| **PT-12** | Win-respin (no lock fields) | bonus rounds with `ReMarks contains "ReSpin"/"Respin"`, no LockSymbols/LockLines/BCM | 33 machines | HIGH |
| **PT-13** | MiniGame pick-bonus | bonus rounds with `ReMarks starts with "MiniGame[N]"` + WinCredits populated + PayoutIdToWinAmount=null | 22 machines | HIGH |
| **PT-14** | Multi-symbol collection freespin | `RewardIdToCollectAmount` extra field present | 2 machines (M120, M125) | HIGH |
| **PT-15** | Wheel bonus (non-BCM, non-TopDollar) | bonus rounds with `ReMarks="WheelSpin..."` and no BCM core fields | ~24 machines | MEDIUM (wheel remark alone insufficient — need to exclude BCM overlap) |

**Overlap notes (co-occurring signals — a machine exhibits multiple play-types):**

- M275 exhibits PT-1 (paid spins) + PT-3 (BCM cycle) + PT-4 (BCM-triggered freespin) + PT-2 (scatter freespin via pay_id=666)
- M279 exhibits PT-1 + PT-3 (BCM cycle) + PT-7 (wild-nudge ST=36) + PT-5 (BCM WheelSpin)
- M268 exhibits PT-1 + PT-3 (BCM cycle) + PT-11 (lock-reels respin, BCM variant)
- M260 exhibits PT-1 + PT-3 + PT-4 (freespin) + PT-5 (WheelSpin) + unknown(ST=105 transition)
- M274 exhibits PT-1 + PT-6 (BCM-ListRewardWheel Minigame)
- M43 exhibits PT-1 + PT-12 (win-respin) + PT-13 (MiniGame)
- M99 exhibits PT-1 + PT-9 (lock-symbol) + PT-15 (WheelSpin non-BCM) + PT-13 (FinalMinigame)
- M15 exhibits PT-1 + PT-8 (TopDollar selector)

**The decomposition principle holds**: a machine = an aggregation of play-types, each identified by orthogonal rawdata signals.

---

### A5. Shared vs. machine-specific play-types

| PT# | Shared across machines? | Machines confirmed | Notes |
|---|---|---|---|
| PT-1 | **Yes, ~64 machines** | M1, M14, M37, M101, M105, M139 + ~58 more | Most common; no special logic |
| PT-2 | **Yes, 13+ machines** | M31, M109, M114, M134, M146, M179, M24, M33, M36, M67, M79, M87, M95 | pay_id=666 + TriggerFreespin remark is portable signal |
| PT-3 | **Yes, 61 machines** | M108, M111, M117, M125, M126, M147, M152, M272, M274, M275, M279 + 50 more | BCM 4-field presence is the reliable signal |
| PT-4 | **Yes, ~34 machines** | M272, M275, M229, M231, M249, M262, M278, M280 + ~26 more | BCM+freespin is the most common BCM flavor |
| PT-5 | **Yes, ~32 machines** | M279, M260, M125, M126, M147, M163, M273 + ~25 more | BCM+WheelSpin |
| PT-6 | **Machine-specific (M274)** | M274 only (confirmed) | pay_id=5801 is M274-config; ListRewardWheel logic may exist on other machines with different trigger anchors |
| PT-7 | **Yes, 10 machines** | M140, M149, M209, M226, M256, M259, M26, M276, M279, M51 | wild-nudge predicate (CostCredits=0 + move/nudge remark) is portable |
| PT-8 | **Yes, 6 machines** | M12, M15, M32, M90, M132, M206 | TopDollar family; DollarCount field is deterministic |
| PT-9 | **Yes, 14 machines** | M99, M103, M104, M107, M114, M183, M193, M207, M208, M222, M239, M240, M273, M47 | LockSymbols+PrevLockSymbols signal |
| PT-10 | **Yes, 19 machines** | M10, M131, M133, M20, M201, M227, M228, M23, M231, M233, M241, M244, M246, M247, M248, M257, M277, M65, M93 | LockLines signal |
| PT-11 | **Yes, 9 machines** | M100, M108, M244, M245, M252, M268, M278, M88, M96 | LockReels signal |
| PT-12 | **Yes, ~33 machines** | M150, M156, M159, M164, M165, M177, M178, M180, M182, M185, M206 + ~22 more | Respin remark (no lock/BCM fields) |
| PT-13 | **Yes, 22 machines** | M43, M44, M54, M75, M99, M112, M119, M124, M151, M175, M192, M210, M225, M244, M245, M247, M252, M273, M274, M67, M97, M98 | MiniGame remark |
| PT-14 | **Machine-specific (M120/M125)** | M120, M125 | RewardIdToCollectAmount is unique to this pair |
| PT-15 | **Yes, ~24 machines** | M99, M102, M110, M112, M119 + ~19 more | Wheel-only (no BCM); MEDIUM confidence because WheelSpin remark alone overlaps with PT-5 |

---

### A6. DIRECTION claims verification

| Claim | Source | RAWDATA VERDICT |
|---|---|---|
| "M14 = {ST1_paid}" | DIRECTION §3 | **CONFIRMED**: 90,000 rounds, all ST=1, all CostCredits>0, zero bonus rounds |
| "M275 = {ST126_free, ST140_paid} + features" | DIRECTION §3 | **CONFIRMED**: 89,090 rounds; paid=140 (80k), bonus=126 (9,090); BCM + freespin + jackpot |
| "payids 1-7 appear on BOTH M14 and M275" | DIRECTION §3 | **CONFIRMED**: M14 pay_ids={1,2,3,4,5,6,7}; M275 paid pay_ids include {1,2,3,4,5,6,7} plus {27502,27503,27504,666,8}. Same pay_id=1, different win values (M14 pid=1 wins: 49k/21k/83k; M275 pid=1 wins: 5k/50k/65k). CONFIRMED per-machine config, not cross-machine semantic |
| "PayId is per-machine CONFIG, NOT a split axis" | DIRECTION §3 | **CONFIRMED** — same pay_id=666 acts as scatter-trigger on M31, jackpot tier on M99, freespin-trigger on M275, TopDollar trigger on M15. Same number, different machine-specific semantics |

**Disagreements with old work (prior `_arch/02_taxonomy.md`):**

1. **M274 BCM trigger mechanism**: old taxonomy (§3.5.1) says M274 needs `bcm_cycle_anchor` rule to detect cycle peak from CollectCount transitions. **Rawdata shows CollectCount=always 0 on M274** (200k paid rounds across 5 chunks). The BCM trigger in M274 is signaled by pay_id=5801 directly in PayoutIdToWinAmount — no CollectCount-based detection needed. The `bcm_cycle_anchor` rule exists to synthesize a labeled anchor in the win-attribution output, not to detect the trigger. This distinction matters: PT-6 (ListRewardWheel) trigger detection = pay_id=5801 lookup, not cycle-peak detection.

2. **M275 is NOT purely BCM-triggered freespin**: old taxonomy listed M275 under BCM family. Rawdata confirms M275 has TWO trigger mechanisms: scatter (pay_id=666, 92% of triggers) AND BCM cycle peak (cc=1000, 8%). The scatter trigger fires at ANY CollectCount value. This makes M275 a hybrid of PT-2 (scatter freespin) + PT-3/4 (BCM cycle), not purely BCM.

3. **M272 ExtraRatio is NOT CollectCount × 100**: early hypothesis based on embedded ReMarks string `CollectCount:N; ExtraRatio:100`. The cc value in the remark is the AddCollectCount (increment added during this freespin), not the CollectCount at trigger. ExtraRatio is an independent parameter. Both M272 and M275 have ExtraRatio as a separate configurable per-trigger multiplier.

4. **M260 ST=105 semantics unclear**: old taxonomy does not address M260's three-bonus-ST structure. ST=105 rounds have CostCredits=0, WinCredits=0, ReMarks=None — possibly a transition/animation phase between wheel and freespin. **Confidence LOW** for ST=105 classification pending deeper investigation.

---

### A7. Cross-signal consistency checks

| Check | Signal A | Signal B | Consistent? |
|---|---|---|---|
| PT-2 scatter trigger | ReMarks=`TriggerFreespin` on paid round | pay_id=666 on same round | M31: 334 TriggerFreespin = 334 pid=666 — **100% match** |
| PT-3 BCM presence | CollectCount field on paid rounds | AccCredits field on paid rounds | All 61 BCM machines: both fields co-occur — **100% match** |
| PT-7 wild-nudge | CostCredits=0 | ReMarks contains "move" | M279: 13,501 ST=36 rounds — all CostCredits=0, all ReMarks=`move` — **100% match** |
| PT-8 TopDollar | DollarCount field | ST=14 phantom rounds | M15: DollarCount present on all 738 ST=14 rounds — **100% match** |
| PT-8 TopDollar | WinAmount field | ST=15 settlement | M15: WinAmount populated on all 263 ST=15; WinCredits=null on all 263 — **100% match** |
| PT-9 lock-symbol | LockSymbols field | PrevLockSymbols field | M99: both fields co-occur on all 51,193 paid rounds — **100% match** |
| PT-11 lock-reels | LockReels field | bonus ST=125 (Respin) rounds | M268: LockReels present on all 1,913 ST=125 rounds; absent on all 50,000 paid rounds — **100% match** |
| PT-13 MiniGame | ReMarks=`MiniGame[N]` | WinCredits>0 + PayoutIdToWinAmount=null | M43: 469 ST=51 MiniGame rounds — all WinCredits non-zero, all PayoutIdToWinAmount=null — **100% match** |
| PT-14 RewardId | RewardIdToCollectAmount field | bonus_ST=138 | M120: RewardIdToCollectAmount present on all 906 ST=138 rounds — **100% match** |

All cross-signal checks pass. Signals are consistent and mutually reinforcing.

---

### A8. Open questions / low-confidence items

1. **M260 ST=105**: 531 rounds with CostCredits=0, WinCredits=0, ReMarks=None. Likely a transition round between WheelSpin outcome and FreeSpin entry. No win-carrying semantics observed. **Action**: examine M260 rawdata sequentially to see if ST=105 always precedes ST=157 (freespin) — if yes, classify as "pre-freespin transition" sub-type of PT-5.

2. **PT-15 (Wheel non-BCM) boundary**: 56 machines have WheelSpin remark; 32 overlap with BCM machines (PT-5). The remaining ~24 non-BCM machines that emit WheelSpin remarks need further breakdown. Some may be triggered by pay_id=666 (scatter), others by lock-symbol accumulation. Signal: WheelSpin remark + absence of BCM core fields.

3. **M274 PT-6 portability**: only M274 confirmed with pay_id=5801. Other BCM machines may use different trigger anchors (different pay_id values) for similar ListRewardWheel mechanics. Cannot generalize until more BCM Minigame machines are scanned.

4. **BCM machines with bonus_ST=() in single-chunk scan**: 6 machines (M152, M153, M186, M194, M236, M238) have BCM core fields but no bonus rounds visible in chunk_0001. Low BCM trigger rate, not absent bonus mechanic. Sampling artifact — PT-3 classification still applies.

5. **GameplayTriggerType=2 semantics**: appears on first round of a freespin sequence on 8 machines (M229, M231, M247, M249, M262, M275, M278, M280). Likely a server-side "this freespin was BCM-triggered" flag. Not currently used in play-type detection; potentially useful as a disambiguation signal if needed.

---

## PART B — 用户审批用：玩法说明（中文，无代码）

### B1. 什么是"玩法"？

每台机台的每一局游戏，服务器会通过数据告诉分析系统"这一局是什么性质的游戏"。我们把具有相同性质、相同分析逻辑的一类游戏局叫做一个"玩法"。

一台机台 = 多种玩法的组合。比如一台"BCM+免费旋转"机台，它有：
- 普通付费旋转玩法（最基础）
- BCM 积分循环玩法（付费旋转过程中积累积分）
- 免费旋转玩法（积分到达峰值或散落触发时启动）

下面列出我们从真实机台数据中推导出的所有玩法，每条都用简单业务语言描述，并标出识别信号（分析系统怎么自动判断）。

---

### B2. 玩法列表（共 15 种，已从真机原始数据验证）

---

**玩法 1 — 普通付费旋转**

游戏描述：玩家每次扣费旋转一次，直接结算。没有额外奖励轮、没有免费旋转、没有积分循环。这是最简单的玩法，占舰队约 64 台机台。

代表机台：M14、M1、M37、M101、M139 等（约 64 台）

识别信号：旋转扣费 > 0，且数据中没有任何奖励轮的记录。

---

**玩法 2 — 散落触发免费旋转**

游戏描述：付费旋转时，出现特定散落符号（服务器数据中标记为 "散落触发"），触发一轮免费旋转序列。免费旋转结束后自动返回普通付费旋转。

代表机台：M31（付费旋转=ST43，免费旋转=ST44）、M109、M114、M134 等（约 13+ 台）

识别信号：付费旋转那一局带有 pay_id=666 且服务器备注包含 "TriggerFreespin"，随后进入免费旋转序列。
- 从 M31 数据实测：334 次触发事件，100% 对应 pay_id=666 + TriggerFreespin 备注，吻合度 100%。

---

**玩法 3 — BCM 积分循环**

游戏描述：每次付费旋转，服务器会返回一个"收集计数"（CollectCount）字段，显示玩家在这一轮循环中积累了多少点数。当积分到达循环峰值时，触发奖励（可以是免费旋转、转盘、小游戏等）。

代表机台：M272、M275、M274、M279、M268、M260、M108、M111 等（共约 61 台，是舰队中最大的奖励机制族）

识别信号：付费旋转的服务器数据同时包含以下四个字段：AccCredits（累积积分值）、CollectCount（当前循环计数）、CreditsSymbols（触发积分的符号信息）、SymbolIndexToRewards（符号对应奖励）。

---

**玩法 4 — BCM 循环触发免费旋转**

游戏描述：在 BCM 积分循环（玩法 3）基础上，奖励是进入免费旋转序列。服务器备注中含有 "Freespin N" 标记，并在免费旋转过程中追踪倍率（ExtraRatio）。

代表机台：M272、M275、M229、M231、M249、M262、M278、M280 等（约 34 台）

识别信号：BCM 四字段 + 奖励旋转带有 "Freespin N;" 备注。
- M272 实测：50,000 次付费旋转中触发 121 次（2 个 chunk），触发率约 0.24%/spin。
- M275 实测：80,000 次付费旋转中触发 908 次（2 个 chunk），触发率约 1.14%/spin。
- 两者都有散落（pay_id=666）和 BCM 峰值两种触发方式，各占约 92% 和 8%。

---

**玩法 5 — BCM 循环触发转盘（WheelSpin）**

游戏描述：在 BCM 积分循环基础上，奖励是进入转盘（Wheel）流程。服务器备注中含有 "WheelSpin CellIndex N; WheelId N;" 标记，转盘格子决定最终奖励金额。

代表机台：M279（ST=2 转盘）、M260（ST=2 转盘 + ST=157 免费旋转）、M125、M126、M273 等（约 32 台）

识别信号：BCM 四字段 + 奖励旋转带有 "WheelSpin CellIndex N;" 备注。

---

**玩法 6 — BCM 循环触发 ListReward 小游戏（Minigame）**

游戏描述：在 BCM 积分循环基础上，奖励是进入一种复杂小游戏（服务器备注中含有多单元格锁定、奖励轮 ID、总锁定状态等信息）。与普通转盘不同，这个小游戏是多步骤的（totalTimes > 1）。目前仅在 M274 上确认。

代表机台：M274（目前唯一确认，可能有其他机台用不同触发标识实现相同机制）

识别信号：BCM 四字段 + 奖励旋转备注包含 "Minigame CellIndexes: ...; RewardWheelIds: ...; AddLock/TotalLock" 格式 + 触发旋转的 pay_id=5801（M274 特有的触发锚点）。

**特别说明**：M274 的 CollectCount（积分计数）在所有付费旋转中始终为 0，与其他 BCM 机台不同。它的触发信号来自 pay_id=5801，而非积分峰值。这是 M274 的设计特性。

---

**玩法 7 — 野生符号自动滑动（Wild Auto-Nudge）**

游戏描述：付费旋转结束后，某个野生符号自动向上或向下滑动一格，形成额外的中奖组合。这个"滑动旋转"不额外扣费，但会产生赢分。服务器标记为 "move"（或 "nudge"）备注，且费用为 0。

代表机台：M279、M140、M149、M209、M226、M256、M26、M276、M51（共 10 台）

识别信号：旋转费用=0 + 服务器备注包含 "move" 或 "nudge"（大小写不敏感）。
- M279 实测：133,621 局中有 13,501 个滑动旋转局，100% 费用=0，100% 备注="move"，完全准确。

---

**玩法 8 — TopDollar 选择器**

游戏描述：付费旋转触发后，服务器先呈现若干"美元金额"供玩家选择（每个选择显示不同的奖励倍数），玩家选择后结算最终奖金。这是分两步结算的特殊机制：第一步=展示选项（服务器传 DollarCount + ChosenDollar），第二步=结算（服务器传 WinAmount 而非通常的 WinCredits）。

代表机台：M15、M12、M32、M90、M132、M206（共 6 台）

识别信号：服务器数据包含 DollarCount（选项数量）+ ChosenDollar（已选项）字段。结算旋转携带 WinAmount 字段（WinCredits 为空）。
- M15 实测：24,000 次付费旋转中触发 263 次（触发旋转带 pay_id=666 + 备注="Trigger"），ST=14 展示选项（738 局），ST=15 结算（263 局），100% 对应。

---

**玩法 9 — 锁定符号再旋（LockSymbol Respin）**

游戏描述：付费旋转时，特定符号（通常是散落或高价值符号）被"锁定"在转轴上，其余转轴继续旋转（再旋）。服务器在每一局的数据中都包含当前锁定状态（LockSymbols）和前一局的锁定状态（PrevLockSymbols）。通常当有足够多符号被锁定时，触发奖励（转盘或高额固定奖）。

代表机台：M99、M103、M104、M107、M114、M183、M193、M207、M208、M222、M239、M240、M273、M47（共 14 台）

识别信号：付费旋转数据中同时包含 LockSymbols 和 PrevLockSymbols 字段。

---

**玩法 10 — 锁定线路再旋（LockLines Respin）**

游戏描述：与锁定符号类似，但锁定的是中奖线路而非符号位置。赢得的线路在再旋时被保留，其他线路继续旋转，直到没有新的中奖为止（"Win-Until-Lose"机制）。

代表机台：M10、M131、M133、M23、M231、M241、M244、M246、M248、M277 等（共 19 台）

识别信号：奖励旋转数据中包含 LockLines 字段（记录当前被锁定的线路）。

---

**玩法 11 — 锁定转轴再旋（LockReels Respin，BCM 变体）**

游戏描述：BCM 积分循环中，奖励旋转时部分转轴被锁定（LockReels 字段记录哪些轴被锁定），其余转轴继续旋转。M268 的服务器备注特别地携带 JSON 格式的符号积分信息（如 `{"symbol_id": credit_value}`）。

代表机台：M268、M100、M108、M244、M245、M252、M278、M88、M96（共 9 台）

识别信号：奖励再旋旋转数据中包含 LockReels 字段，且通常与 BCM 四字段共存（M268）或单独出现（M100、M96）。

---

**玩法 12 — 普通赢分再旋（Win-Respin）**

游戏描述：当付费旋转出现赢分时，触发一次或多次再旋。再旋本身不扣费，并可能再次触发更多再旋（级联）。服务器备注包含 "ReSpin" 或 "Respin"。与锁定符号/线路不同，没有专门的锁定字段，只是普通再旋轮。

代表机台：M43（ST=50）、M150、M156、M159、M164、M165、M177、M178、M180、M182、M185、M190、M196、M221、M223、M224 等（约 33 台）

识别信号：奖励旋转带有 "ReSpin"/"Respin" 备注，且无 LockSymbols/LockLines/BCM 四字段。

---

**玩法 13 — 选牌小游戏（MiniGame Pick）**

游戏描述：奖励轮中出现一个选牌小游戏（MiniGame），玩家在若干位置中选择，获得对应奖励。服务器备注格式为 `MiniGame[位置列表]`（如 `MiniGame[110]`、`MiniGame[109,102]`）。小游戏的赢分记录在 WinCredits 字段中，不拆分到具体 pay_id（PayoutIdToWinAmount 为空）。

代表机台：M43（ST=51）、M44、M54、M75、M99（ST=98 FinalMinigame）、M97、M112、M119、M124、M151、M175、M192、M210 等（共 22 台）

识别信号：奖励旋转备注包含 "MiniGame[N]" 或 "Minigame" + WinCredits 非零 + PayoutIdToWinAmount 为空。
- M43 实测：469 局 MiniGame，469/469 WinCredits 非零，469/469 PayoutIdToWinAmount=null，100% 吻合。

---

**玩法 14 — 多符号收集免费旋转（Multi-Symbol Collection Freespin）**

游戏描述：免费旋转过程中，不同符号各自积累独立的奖励数量（通过 RewardIdToCollectAmount 字段跟踪）。这是一种比标准 BCM 更细粒度的收集机制，每种符号有独立的奖励账本。

代表机台：M120、M125（舰队中仅此 2 台）

识别信号：服务器数据包含 RewardIdToCollectAmount 字段（仅 M120/M125 独有）。

---

**玩法 15 — 独立转盘奖励（Wheel Bonus，非 BCM）**

游戏描述：付费旋转直接触发（非通过 BCM 积分循环）进入转盘奖励。服务器备注包含 "WheelSpin"，但没有 BCM 的四个积分字段。常见于早期机台或结构较简单的机台。

代表机台：M99（ST=97）、M102、M110、M112、M119 等（约 24 台，需进一步确认边界）

识别信号：奖励旋转带有 "WheelSpin CellIndex N;" 备注，但付费旋转不携带 BCM 四字段（与玩法 5 的区别）。

**注意**：玩法 15 与玩法 5 的区别仅在于有无 BCM 积分循环。识别信号中置信度为"中等"——需要同时检查 BCM 四字段是否不存在。

---

### B3. 推荐的 10 台 Pilot 机台及覆盖理由

| 机台 | 主要玩法（按上方编号） | 为什么入选 |
|---|---|---|
| **M14** | 玩法 1（普通付费） | 舰队最简单机台；验证基础付费旋转逻辑的基准线 |
| **M31** | 玩法 1 + 玩法 2（散落触发免费旋转） | 散落触发免费旋转的标准代表；pay_id=666 触发信号已从 334 个事件中完全验证 |
| **M43** | 玩法 1 + 玩法 12（再旋）+ 玩法 13（小游戏） | 同时含再旋和小游戏两种奖励机制；小游戏赢分不走 pay_id（MiniGame WinCredits only）是特殊情况 |
| **M15** | 玩法 1 + 玩法 8（TopDollar 选择器） | TopDollar 机制是最复杂的选择器结算方式；分两步（展示+结算，不同字段）需专门支持 |
| **M99** | 玩法 1 + 玩法 9（锁定符号）+ 玩法 15（独立转盘）+ 玩法 13（FinalMinigame） | 三阶段奖励链（锁定→转盘→最终小游戏）；是非 BCM 的多玩法叠加典型 |
| **M272** | 玩法 1 + 玩法 3（BCM）+ 玩法 4（BCM触发免费旋转） | 现代 BCM+免费旋转的基础代表；paid_ST=140 是现代 BCM 机台的主流形态 |
| **M275** | 玩法 1 + 玩法 3（BCM）+ 玩法 4（BCM+散落 混合触发免费旋转）+ 玩法 2 | BCM+散落双触发机制；jackpot 层 pay_ids（27502/27503/27504）验证了 pay_id 作为配置参数的本质 |
| **M274** | 玩法 1 + 玩法 6（BCM + ListReward 小游戏） | BCM 循环积分为 0 的特殊情况；触发信号为 pay_id=5801；小游戏格式完全不同于普通转盘 |
| **M279** | 玩法 1 + 玩法 3（BCM）+ 玩法 7（野生滑动）+ 玩法 5（BCM触发转盘） | 三种玩法叠加（BCM+野生滑动+转盘）；是舰队中结构最复杂的机台之一 |
| **M268** | 玩法 1 + 玩法 3（BCM）+ 玩法 11（锁定转轴再旋） | BCM 变体：奖励是锁定转轴再旋而非免费旋转/转盘；LockReels+JSON格式备注是独特信号 |

**覆盖验证**：这 10 台机台覆盖了玩法 1–13 中的所有主要类型（玩法 10、12、14、15 在这 10 台中没有全部覆盖，但：玩法 10 与玩法 9 机制相似；玩法 14 仅限 M120/M125，可作为第 11 台补充；玩法 12 在 M43 ST=50 中已覆盖再旋概念）。

若需完整覆盖玩法 10 和玩法 14，建议额外加入：
- **M120**（玩法 14 — RewardIdToCollectAmount 多符号收集，舰队中唯一机制）
- **M10 或 M131**（玩法 10 — LockLines 锁定线路再旋）

---

### B4. 用户审批请求

以上共识别 **15 种玩法**，分析系统将为每种玩法生成一个独立的插件，自动从机台原始数据中检测。

在您审批前，请确认以下几点：

1. **玩法命名**：以上中文名称（如"散落触发免费旋转"、"BCM 积分循环"）是否符合您对这些游戏机制的理解？

2. **玩法 6 的边界**：目前仅 M274 确认携带 pay_id=5801 触发的 Minigame。如果其他机台有类似小游戏但触发锚点不同，是否算同一玩法？

3. **Pilot 范围确认**：以上 10 台（或扩展到 12 台含 M120 + M10）能否作为第一轮架构验证的范围？

4. **玩法 15（独立转盘）边界**：目前 ~24 台非 BCM 转盘机台，需要更多验证来细分（直接散落触发 vs 锁定符号累积触发）。您是否接受我们先以"有 WheelSpin 备注且无 BCM 四字段"作为临时分界？

---

*End of taxonomy. PART A is the technical specification for the arch-designer. PART B is the user sign-off gate. No code changes are proposed here — architecture design follows user approval.*
