# Fleet Taxonomy — rawdata / analyzer / console pipeline

> Wave 1 deliverable from `arch-taxonomist`. Data-driven clustering of the
> 421-row machine fleet across five structural axes, with cross-axis
> co-cluster analysis and outlier inventory. Strictly descriptive — no
> design opinions (those are arch-designer's job).
>
> **Sampling**: rawdata/ contains 302 machine dirs; 206 had loadable
> `mode_1/chunk_*.json` for full schema/SpinType fingerprinting. Variants
> were fingerprinted only where rawdata is present (47 of 166 variant
> rows). The 215 machines without rawdata-mode_1 are still classifiable
> on Axes 2, 3, 5 via `configs/machines.json.logicClassNames` plus
> `configs/machine_selector_types.json` / `configs/bcm_pairings.json` /
> `configs/machine_round_win_rules.json`. Per the brief §8 these signals
> are treated as sufficient ground truth.
>
> **Date**: 2026-05-15

---

## §1 Scope & inventory

### Fleet under classification

| Source | Count | Note |
|---|---|---|
| `configs/machines.json` rows | **421** | full registry, brief §8 |
| Non-variant rows | **255** | one `machine` field per row, no `$` |
| Variant rows | **166** | underlying `M<N>$<Selector>$<index>$<suffix>` |
| Unique variant **underlying** machines | **26** | each spawns 2-85 variants |
| Non-variant rows that are NOT variant underlyings (pure machines) | **229** | |
| rawdata/ dirs on disk | **302** | 255 non-variant + 47 variant |
| rawdata machines with `mode_1` chunks loadable | **206** | base for Axes 1, 3, 4 fingerprinting |
| Machines with explicit `configs/machine_round_win_rules.json` entry | **13** | M274 + TopDollar variants (M12/M15/M90/M132 × 3 variants) |
| Machines with `configs/bcm_pairings.json` entry | **30** | BCM cycle pairings (10 distinct bonus_feature labels) |
| `slot_designer/machines/<M>/spec.json` virtual machines | **6** | M1, M15, M31, M37, M43, M279 |

### Sampling strategy

Per brief §8 (rawdata coverage is partial) the analysis uses three tiers:

1. **Full-fleet inventory signals** (every row in `configs/`):
   `logicClassNames`, `machine_selector_types`, `bcm_pairings`,
   `machine_round_win_rules`. Used for Axes 2 + 5 across all 421 rows.
2. **rawdata-fingerprinted** (206 machines with `mode_1/chunk_0001.json`
   readable): SpinType convention (Axis 1), schema-extras (Axis 4),
   paytable structure (Axis 3). Variants under-represented; flagged
   where it matters.
3. **Brief-mandated representative sample** (re-checked deeply across
   all 5 axes): `M1`, `M14`, `M15`, `M37`, `M99`, `M120`, `M139`,
   `M260`, `M268`, `M272`, `M274`, `M279`, `M31`, `M43`, plus variants
   `M12$TopDollarSelector$0$`, `M273$WheelSelector$0$`,
   `M201$CommonSelector$0$`, plus context outliers `M21`, `M11`, `M5`,
   `M65`, `M250`. Used as ground truth for the cross-axis matrix (§4).

### Counts will not always sum to 421

- Axis 1 (SpinType) sees only the 206 rawdata-fingerprinted machines.
- Axis 4 (rawdata schema) sees the same 206.
- Axis 2 (feature shape) sees all 421 via `logicClassNames` proxy.
- Axis 3 (paytable) sees the 206; specific paytable-line / reel-count
  numbers are sample-based.
- Axis 5 (rule reliance) sees all 421 via `configs/`.

The brief explicitly allows sample-based analysis when coverage is partial.

---

## §2 Clustering axes

Five axes selected per brief §"Required clustering axes (≥3)":

| # | Axis | Primary signal | Data source | Coverage |
|---|---|---|---|---|
| 1 | **SpinType convention** | which `SpinType` ints denote paid vs bonus rounds | `rawdata/<M>/mode_1/chunk_0001.json.response[*].roundResult[*].SpinType` + `CostCredits` | 206 |
| 2 | **Feature/round-class shape** | which bonus mechanism the machine implements (BCM cycle, TopDollar selector, lock-respin, freespin, wheel, nudge, …) | `configs/machines.json.logicClassNames` + `configs/machine_selector_types.json` + `configs/bcm_pairings.json` | 421 |
| 3 | **Paytable structure** | reel count, payline count, distinct pay_id count, presence of wild / scatter / jackpot tiers | `rawdata.PayoutByPayline` line_ids + `PayoutIdToWinAmount` keys + `StopSymbolsByCol` list length | 206 |
| 4 | **Rawdata schema fingerprint** | which `roundResult` JSON keys this machine emits beyond the 17-key base envelope | `rawdata` chunk[0] union-of-keys across all rounds in the chunk | 206 |
| 5 | **round_win_rules + round_classification reliance** | which `fresh_slotlab/round_win.py` rule class + `round_classification.py` primitive functions each machine actually depends on | `configs/machine_round_win_rules.json.rules[*].applies_to` + `bcm_pairings.machines[*]` + `slot_designer/machines/<M>/spec.json.features` | 421 |

Axes 1 and 4 are **rawdata-observed** (machine-emitted truth);
Axes 2 and 5 are **config-declared** (operator-declared truth);
Axis 3 is mixed (rawdata for hard counts, config for trim).

---

## §3 Per-axis clusters

### §3.1 — Axis 1: SpinType convention (206 machines)

84 distinct (paid_ST_set, bonus_ST_set) signatures. Distribution is
power-law: the top 13 signatures cover **143 of 206 (69%)**, and 63
signatures are singletons.

| Cluster | n | paid ST | bonus ST | Sample members | Notes |
|---|---|---|---|---|---|
| **ST-1A "Vanilla paid=1, no bonus"** | 54 | `{1}` | `{}` | M1, M101, M105, M106, M127, M13, M135, M137, M139, M14, M37, M142, M143 | Bonus mechanic is encoded as in-grid (wild nudge, payline-only); upstream emits one ST for paid only. Largest single cluster. |
| **ST-1B "Paid=1 + Bonus=2"** | 10 | `{1}` | `{2}` | M151, M158, M175, M211, M213, M214, M217, M3 | Wheel- / NewFreespin-trigger machines using the upstream "ST=2 bonus" convention. |
| **ST-1C "Paid=1 + Bonus=50"** | 9 | `{1}` | `{50}` | M150, M156, M159, M164, M177, M221, M223, M224 | LockRespin family — ST=50 = "respin until lose / hit". |
| **ST-1D "Paid=1 + Bonus=126"** | 8 | `{1}` | `{126}` | M166, M167, M181, M184, M199, M202, M212, M243 | NewFreespin / late-fleet bonus token. |
| **ST-1E "Paid=140 + Bonus=126"** | 6 | `{140}` | `{126}` | M253, M263, M264, M265, M271, M272 | Recent BCM family, paid-ST shifted to 140. |
| **ST-1F "Paid=1 + Bonus=117"** | 5 | `{1}` | `{117}` | M114, M183, M193, M208, M222 | LockSpin / lock-symbol respin family. |
| **ST-1G "Paid=43 + Bonus=44"** | 5 | `{43}` | `{44}` | M134, M146, **M31**, M79, M95 | "Sevens & Sevens" archetype — Scatter-trigger freespin. |
| **ST-1H "Paid=35 + Bonus=36"** | 5 | `{35}` | `{36}` | M140, M149, M226, M26, M51 | MoveSpin / nudge — ST=36 is the wild-nudge continuation (memory: `round_classification.is_wild_nudge_round`). |
| **ST-1I "Paid=140, no bonus token"** | 5 | `{140}` | `{}` | M152, M153, M186, M194, M238 | Plain-Modern (paid-ST migrated to 140 but no bonus surfaces in rawdata sample). |
| **ST-1J "Paid=1, Bonus={50,126}"** | 5 | `{1}` | `{50, 126}` | M165, M178, M180, M182, M185 | LockRespin + freespin combo. |
| **ST-1K "No paid, only Bonus=13"** | 4 | `{}` | `{13}` | M10, M131, M133, M23 | LockLines respin family — paid spins use cost=0 (free token after first), all rounds appear as bonus by `is_paid_round`. Sampling artifact: paid_set empty in chunk_0001. |
| **ST-1L "Paid=1, Bonus={14,15}" (TopDollar Selector)** | 4 | `{1}` | `{14, 15}` | **M15**, M15$TopDollarSelector$0$, M15$TopDollarSelector$1$, M15$TopDollarSelector$2$40 | Selector trigger family: 14=phantom offer, 15=settlement (handled by `SettlementWinAmountRule`). |
| **ST-1M "Paid=1, Bonus={50,51}"** | 4 | `{1}` | `{50, 51}` | **M43**, M44, M54, M75 | LockRespin + Minigame combo (M43 archetype). |

#### Axis 1 outliers (63 singleton signatures, sample):

| Machine | paid ST | bonus ST | Notable |
|---|---|---|---|
| **M99** | `{96}` | `{97, 98}` | Lock-symbol respin; two distinct bonus ST values (memory: M99/M112 ST=97+98 dedupe pending). |
| **M112** | `{1}` | `{97, 98}` | Same dual-bonus pattern as M99 but with paid=1. |
| **M260** | `{156}` | `{2, 105, 157}` | Three-class bonus chain (Wheel + ListReward + something). |
| **M279** | `{140}` | `{2, 36}` | BCM cycle to Wheel + MoveSpin wild-nudge. Memory cites this as "custom engine". |
| **M274** | `{140}` | `{139}` | Single bonus ST = 139, the only machine sharing this sig with M192. |
| **M268** | `{140}` | `{125}` | CreditsSymbolRespin (per bcm_pairings). |
| **M272** | `{140}` | `{126}` | Co-located with cluster ST-1E (NewFreespin BCM). |
| **M120** | `{1}` | `{138}` | RewardIdToCollectAmount-mechanic; the only ST=138 bonus machine. |
| **M21** | `{27}` | `{25}` | Buffalo-themed; the only machine with named-symbol counters (`Buffalo`, `Deer`, `Eagle`, `Tiger`, `Wolf`). |
| **M65** | `{70}` | `{}` | CollectCollection mechanic but no bonus ST surfaces in chunk_0001 — sampling artifact likely. |
| **M11** | `{17}` | `{10, 11, 12}` | Diamond-heart fortune mechanic with multi-stage bonus. |
| **M97** | `{87, 88}` | `{89}` | Two paid ST values (rare); pond/cell collection. |

**Headline**: paid-ST is overwhelmingly `1` (~95+ machines) or `140`
(~25+ machines, all recent BCM). Bonus-ST is the dimension that
fragments into many small clusters.

### §3.2 — Axis 2: Feature/round-class shape (421 machines, logicClassNames-based)

Tagging from `logicClassNames` substrings. Multi-tag (a machine can be
`{BCM, Wheel, FreeSpin}` simultaneously); 35 distinct tag combinations
on non-variant fleet, 64 of 255 non-variant machines are pure-`{Plain}`.

| Cluster | n | Tag combo | Mechanism |
|---|---|---|---|
| **F-Plain** | 64 | `{Plain}` | Only `NormalSpinGenerator` family. No declared bonus mechanism in code. 45 of these match the **exact** signature `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` — these are the "fully vanilla" core machines. |
| **F-FreeSpin** | 39 | `{FreeSpin}` | Single freespin trigger (no wheel / lock / collection extras). |
| **F-LockRespin** | 25 | `{LockRespin}` | Win-respin / lock-respin without scatter freespin. |
| **F-BCM+FS+Wheel** | 15 | `{BCM, FreeSpin, Wheel}` | The "modern BCM + freespin + wheel" archetype (memory: BCM cycle family). |
| **F-BCM+FS** | 15 | `{BCM, FreeSpin}` | BCM + freespin without wheel. |
| **F-Wheel** | 13 | `{Wheel}` | Pure wheel bonus, no freespin or BCM. |
| **F-FS+Wheel** | 9 | `{FreeSpin, Wheel}` | Combined FS + wheel, no collection. |
| **F-BCM+Wheel** | 9 | `{BCM, Wheel}` | BCM + wheel, no freespin (e.g. M274 ListRewardWheel). |
| **F-Selector+Wheel** | 8 | `{Selector, Wheel}` | WheelSelector family (M102, M187, M188, etc.) |
| **F-BCM** | 7 | `{BCM}` | Pure BCM, no freespin/wheel (e.g. M152, M268). |
| **F-BCM+LockRespin+Wheel** | 6 | `{BCM, LockRespin, Wheel}` | M163, M227, M228, M232, M233, M242. |
| **F-FS+LockRespin** | 5 | `{FreeSpin, LockRespin}` | M165, M178, M180, M182, M185 — combo bonus. |
| **F-MoveNudge** | 4 | `{MoveNudge}` | Wild-auto-nudge specialty (M140, M149, M26, M51). |
| **F-LockRespin+Minigame** | 4 | `{LockRespin, Minigame}` | M43, M44, M54, M75 — M43 archetype. |
| **F-FS+Selector** | 4 | `{FreeSpin, Selector}` | FortunesSelector / generic combos. |
| **F-Selector** | 4 | `{Selector}` | M98, **M12**, **M15**, M132 — pure TopDollar archetype. |

#### Axis 2 outliers (singletons + uncommon combos):

| Machine | Tag combo | Why outlier |
|---|---|---|
| **M226** | `{LockRespin, MoveNudge}` | Only machine combining lock-respin with wild-nudge. |
| **M231** | `{BCM, FreeSpin, LockRespin}` | Triple combo absent elsewhere. |
| **M24** | `{FreeSpin, Minigame}` | Pig/Gold mechanic — own logic family. |
| **M241** | `{LockRespin, Wheel}` | Rare pairing. |
| **M244** | `{BCM, LockRespin}` | Rare pairing. |
| **M276 / M279** | `{BCM, MoveNudge, Wheel}` | Three-feature combo (M279 memory: "custom engine"). |
| **M256** | `{BCM, FreeSpin, MoveNudge}` | Three-feature combo. |
| **M259** | `{BCM, FreeSpin, MoveNudge, Wheel}` | Four-feature combo — the most-fragmented machine on this axis. |
| **M93** | `{FreeSpin, LockRespin, Wheel}` | Rare triple. |
| **M90** | `{BCM, Selector}` | TopDollar + collection mechanic. |
| **M201, M209, M257** | `{*, Selector}` with `CommonSelector` | Generic 3-of-N selectors — variant explosion (M273 alone has 85 variants). |
| **M261, M273** | `{BCM, FreeSpin, Selector, Wheel}` | Most-features-stacked machine without exotic tags. |
| **M247** | `{BCM, MoveNudge, Selector, Wheel}` | Four-tag — variant-heavy. |

### §3.3 — Axis 3: Paytable structure (206 machines)

#### §3.3.1 Payline count (distinct line_id values in PayoutByPayline)

| line_id count | n | Sample members | Interpretation |
|---|---|---|---|
| **1** | 45 | M1, M101, M105, M112, M131, M145 | Classic 1-payline (memory: classic Liberty Bell / Blazing Sevens style). |
| **2** | 21 | M15, M181, M192, M15$variants$ | 2-line; mostly TopDollar (M15) and recent paid=140 machines. |
| **3** | 3 | M250, M263, M36 | Rare 3-line. |
| **4** | 2 | M21, M95 | M21 = 4-symbol special; M95 = small custom. |
| **5** | 16 | M10, M110, M133, M139, M148, M170 | 5-line standard. |
| **6** | 20 | M103, M138, M146, M147, M167, M18, M268 | 6-line; common BCM family. |
| **7** | 9 | M111, M114, M120, M130, M238, M266, M31 | 7-line (M31 sits here). |
| **8** | 2 | M33, M93 | Rare. |
| **9** | 42 | M100, M104, M11, M122, M127, M13, M14, M279 | Second-largest cluster; classic 3-reel 9-payline. |
| **10** | 16 | M109, M124, M128, M144, M152, M153, M272 | Modern 10-line. |
| **11** | 6 | M134, M136, M171, M174, M246, M97 | |
| **12, 15, 20** | 1+1+1 | M121, M160, M199 | Singletons. |
| **21** | 4 | M176, M212, M60, M79 | 21-line variant. |
| **27, 28, 29** | 1+4+2 | M67; M106, M125, M24, M64; M119, M225 | Mid-line. |
| **31** | 5 | M108, M126, M168, M5, M88 | Higher-line. |
| **42, 43** | 2+1 | M129, M27; M107 | High-line. |
| **60** | 1 | **M260** | Far outlier — the largest payline count in fleet. |
| **81** | 1 | **M113** | Largest of all (`ExpandedSymbols` mechanic). |

#### §3.3.2 Reel count (length of `StopSymbolsByCol` list)

| Reels | n | Sample | Note |
|---|---|---|---|
| **3** | 178 | M1, M10, M100, M101, M14, M15 | Dominant — classic 3-reel format. |
| **4** | 5 | M113, M169, M178, M197, M4 | 4-reel rare. |
| **5** | 18 | M107, M108, M126, M137, M168, M176, M21, M22 | Modern 5-reel video-slot style. |
| **6** | 1 | M24 | Singleton. |
| **9** | 3 | M129, M239, M96 | Likely 3×3 grid layout encoded as 9-reel. |
| **20** | 1 | **M250** | Far outlier — 20-reel grid (multi-row collection layout). |

#### §3.3.3 Distinct pay_id count

| Range | n | Sample |
|---|---|---|
| 1-5 | 11 | M121, M139, M172, M214, M226, M241, M250, M254 |
| 6-10 | 138 | M1, M10, M14, M15, M31, M37, M99 (most of fleet) |
| 11-15 | 39 | M100, M103, M110, M111, M125 |
| 16-25 | 11 | M108, M114, M126, M168, M176, M22 |
| 26+ | 7 | M106, M107, **M260** (54), M27, M5, M60, M67 |

#### §3.3.4 Special pay_id markers (jackpot / trigger / synthetic)

| Marker | Machines | Source |
|---|---|---|
| `pid=666` (TopDollar trigger anchor) | M12/M15/M90/M132/M206 + variants, M120 | memory + rawdata sweep |
| `pid=5801` (M274 ListRewardWheel trigger anchor) | M274 | memory `feedback_invariant_with_fallback_hides_drift.md` |
| `pid=27905` / `104` (M279 jackpot tier, suffix-attribution Bug 1) | M279 | round_classification.attribute_lines_to_pay_ids docstring |
| `pid=109/9`, `55/5` (suffix-attribution) | M120, M139 | round_classification |
| `pid="1110"-"1119"` and similar 4-digit | M260 | rawdata sample |
| Synthetic `pid="_bcm_cycle"` (M274 BCM cycle anchor) | M274 (planned: M250, M268, M260, M264, M163, M147) | `BCMCycleAnchorRule` |
| Synthetic `pid="_unattributed_st<N>"` (fallback bucket) | any with leakage | memory `feedback_invariant_with_fallback_hides_drift.md` |

### §3.4 — Axis 4: Rawdata schema fingerprint (206 machines)

The `roundResult[0]` dict uses a **17-key base envelope** that 147 of
206 (71%) machines emit verbatim. The remaining 59 machines emit
additional keys — clustering on the extras-set reveals the mechanism
families:

| Cluster | n | Extras keys (delta from 17-key base) | Sample members | Mechanism |
|---|---|---|---|---|
| **S-Base** | 147 | `{}` (exactly base 17) | M1, M14, M15, M31, M37, M43, M120, M139, M272, M274, M279, M99 (with LockSymbols variant), M101, M105, M109, M110, M112, M114 | 71% of fingerprinted fleet shares the exact envelope. |
| **S-BCM-21k** | 28 | `+{AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards}` | M108, M111, M125, M126, M147, M152, M153, M163, M186, M192, M194, M238, M250, M253, M256, M263, M264, M265, M268, M269, M271, M272, M274, M279, others | BCM cycle machines emit collection counter + per-symbol rewards. **Note**: M272 and M274 have additional / different extras (see below) — 21 of these 28 have the exact 4-extras tuple. |
| **S-LockSym** | 5 (re-fingerprinted as 8) | `+{LockSymbols, PrevLockSymbols}` | M103, M104, M114 (no), M183 (no), M99, M240 | Lock-symbol respin. M99 is here. |
| **S-LockLines** | 5 | `+{LockLines}` | M10, M131, M133, M23, M241 | Lock-payline respin (ST-1K cluster). |
| **S-TopDollar** | 4 | `+{ChosenDollar, DollarCount, ExtraRatio, JackpotIds, OfferValue, WinAmount}` | M15 + 3 variants | TopDollar selector (full M15 family). |
| **S-AddFS** | 3 (also see singletons) | `+{AddFreeSpin, CurFreeSpin, LeftFreeSpin, ...}` | M27, M33, M36 | Older AddFreeSpin-style FS counter. |
| **S-Lock-LockLines-Collection** | 2 | `+{AccCredits, CollectCount, CreditsSymbols, LockLines, SymbolIndexToRewards}` | M246, M277 | BCM + LockLines combo. |
| **S-FreeSpinEnter** | 3 | `+{FreeSpinEnter}` | M129, M136, M28 | Older enter-trigger pattern. |

#### Axis 4 outliers (singleton extras-signatures):

| Machine | Extras | Mechanism marker |
|---|---|---|
| **M100** | `{CreditsBySymbol, LockReels}` | Reel-lock + per-symbol credits. |
| **M103** | `{JackpotID, LockSymbols, PrevLockSymbols, TriggerCount}` | Lock + jackpot tier. |
| **M107** | `{CollectCount, JackpotID, LastCollectCount, LockSymbols, PrevLockSymbols, TriggerCount}` | Lock + collection + jackpot triple. |
| **M108** | `{AccCredits, CollectCount, CreditsSymbols, FillUpTo, LockReels, ReelCollect, ShouldUpdateFillUpTo, SymbolIndexToRewards}` | Reel-collect fill-up — most unique BCM. |
| **M11** | `{DiamondCount, FreeSpinRewardCount, FreeSpinTimes, GoldDiamondCount, HeartRatios, JackpotIds, TotalFreeSpinTimes, TotalRatio}` | Diamond/heart fortune. |
| **M110** | `{Balls}` | Ball-collection only machine in fleet. |
| **M113** | `{ExpandedSymbols}` | Expanding-wild — only one. |
| **M119** | `{AccAmount, Multiplier}` | Multiplier accumulator. |
| **M120** | `{RewardIdToCollectAmount}` | RewardId mechanic — singleton. |
| **M121** | `{Level}` | Level-up machine — singleton. |
| **M122** | `{CurGameCount, SymbolIndexToFrameLevel}` | Per-symbol frame-level (only one). |
| **M138** | `{AllWinIndexes, AllWinLines, CollectRatio, CollectedIndexes, CurWinIndexes, CurWinLines}` | All-ways-pay variant. |
| **M18** | `{JackpotIds, TntReels}` | TNT theme. |
| **M20** | `{JackpotIds, LockLines}` | Jackpot + LockLines combo. |
| **M21** | `{Buffalo, Deer, Eagle, GoldenBuffalo, GoldenBuffaloIndexes, Tiger, TotalGoldenBuffalo, Wolf}` | Per-animal counter — the **most-bespoke** machine in fleet (themed-symbol counters). |
| **M22** | `{DoubleSymbolReward}` | Double-symbol reward. |
| **M239** | `{AccCredits, CollectCount, CreditsSymbols, LockSymbols, PrevLockSymbols, SymbolIndexToRewards}` | BCM + lock-symbol combo. |
| **M24** | `{CollectGoldCount, PigCredits, TotalCollectGoldCredits}` | Pig/gold themed counter. |
| **M251** | `{AccCredits, BuffTypes, CollectCount, CreditsSymbols, ReelIdToCollectionDatas, RewardIdToIndexes, SymbolIndexToRewards}` | BuffTypes — singleton extension of BCM. |
| **M254** | `{AccCredits, BuffTypes, CollectCount, CreditsSymbols, RewardIdToIndexes, SymbolIndexToRewards}` | Similar to M251 but no ReelIdToCollectionDatas. |
| **M260** | `{AccCredits, Buffs, CollectCount, CreditsSymbols, IncreasedCredits, IndexToCreditPool, NodeIndex, ReelIdToSpinData, ReelIdToWheelData, SymbolIndexToRewards}` | **10-key delta** — by far the largest, plus `Buffs` is unique to M260. The most-extended BCM machine. |
| **M266** | `{AccCredits, CollectCount, CreditsSymbols, IndexToCreditPool, ReelIdToSpinData, ReelIdToWheelData, SymbolIndexToRewards}` | Close cousin of M260 without `Buffs/IncreasedCredits/NodeIndex`. |
| **M268** | `{AccCredits, CollectCount, CreditsBySymbol, CreditsSymbols, LockReels, SymbolIndexRatio, SymbolIndexToRewards}` | BCM + reel-lock + dual credits encoding. |
| **M65** | `{CollectCollectionIndexes, CollectCount, LastCollectCount, LockLines, ShowCollectionIndexes, TotalPrize, WinAmount}` | Old collection format with explicit indexes. |
| **M67** | `{ClosedIds, OpenedIds}` | Open/closed cells — singleton. |
| **M76** | `{BonusDiamondGoal, DiamondLives, DiamondsCollectedAmount}` | Diamond bonus goal — singleton. |
| **M96** | `{LockReels}` | LockReels only — singleton. |
| **M97** | `{CellIndex, CollectCount, PondId}` | Pond mechanic. |
| **M98** | `{AccumulatedCredits, CoinsRemaining, TotalCoins}` | Coin-bank — singleton. |

**Headline**: 71% of fingerprinted machines fit the 17-key base envelope.
The BCM-cycle extras (`AccCredits, CollectCount, CreditsSymbols,
SymbolIndexToRewards`) cluster into a 21-key envelope used by 28
machines. Beyond that the long tail is dominated by **theme-specific
counters** (Buffalo, Diamond, Pig, Pond, etc.) that no two machines
share.

### §3.5 — Axis 5: round_win_rules + round_classification reliance (421 machines)

This axis is **machine-specific code reliance** — which analyzer primitives
each machine actually depends on. Two layers:

#### §3.5.1 Explicit `RoundWinRule` registrations (`configs/machine_round_win_rules.json`)

Only **13 of 421 machines** carry an explicit per-machine rule
registration. Default behaviour is byte-identical-to-legacy for all
others. (Per `round_win.py` module docstring.)

| Rule type | Machines | Mechanism |
|---|---|---|
| `bcm_cycle_anchor` | **M274** (only 1) | Synthesizes `_bcm_cycle` trigger anchor on paid rounds at `CollectCount==cycle_peak` when `PayoutIdToWinAmount` carries no anchor. |
| `settlement_winamount` | 12 machines: M12 / M15 / M90 / M132 × 3 variants each (TopDollarSelector family) | Maps ST=14 phantom offers to 0 win, ST=15 settlement to `WinAmount` field. |

The other **408 machines** rely solely on the legacy default
`WinCredits` + `PayoutIdToWinAmount` extraction with no rule list.

> Per memory `feedback_invariant_with_fallback_hides_drift.md`:
> ~55 of 117 cached BCM (machine, mode) pairs have >0.5% RTP
> falling into the `_unattributed_st<N>` fallback bucket
> (M250 100%, M268/M260/M264 70-90%, M163/M147 ~35%). These
> machines **need** the `bcm_cycle_anchor` rule but haven't been
> enabled yet — they're a known gap in Axis 5 coverage that the
> next-gen architecture should treat as in-scope.

#### §3.5.2 `round_classification.py` primitive reliance (per-machine implicit)

The analyzer's `parse_chunk_response` calls 5 primitives whose
behaviour is machine-dependent. Reliance inferred from rawdata signals:

| Primitive | Triggered for | Triggered by | Members |
|---|---|---|---|
| `is_wild_nudge_round` (Bug 3) | machines emitting `ST=36` + `ReMarks="move"` + `CostCredits=0` | rawdata `ReMarks` substring match | M279, M226, M149, M140, M26, M51, M256 — **7+ confirmed**; memory cites 25 (machine, mode) pairs total. |
| `detect_cycle_peak` (Bug 4) | machines with `CollectCount` field in rounds | rawdata extras contains `CollectCount` | 28 BCM-21-key machines + at least 7 from S-LockSym/S-LockLines/etc — **~35-40 machines**. |
| `at_cycle_peak_indices` | downstream of `detect_cycle_peak` | same | same as above |
| `infer_bcm_target_spin_type` (Bug 2) | BCM machines for paytable inference | same | same |
| `attribute_lines_to_pay_ids` (Bug 1, suffix-fallback) | machines whose symbol_id != pay_id by direct match | rawdata `PayoutByPayline` symbol_id mismatched against `PayoutIdToWinAmount` keys | M120 (109→9), M123 (308→8), M139 (55→5), M279 (27905→104) — **4 confirmed**; suspected more via memory's "30+ machines audited 2026-04-27". |

#### §3.5.3 BCM-pairing declarations (`configs/bcm_pairings.json`, 30 machines)

Distribution of declared `bonus_feature` (mode 1):

| bonus_feature | n | Sample |
|---|---|---|
| `NewFreespin` | 11 | M237, M249, M252, M253, M263, M264 |
| `Wheel` | 7 | M246, M250, M254, M260, M267, M270, M279 |
| `LockReSpin` | 4 | M227, M233, M248, M277 |
| `LockSymbolFreespin` | 1 | M239 |
| `UntilWinRespin` | 1 | M242 |
| `MultiBuffFreespin` | 1 | M251 |
| `MoveSpin` | 1 | M256 |
| `CreditsSymbolRespin` | 1 | M268 |
| `UntilLoseRespin` | 1 | M269 |
| `ListRewardWheel` | 1 | M274 |

10 distinct bonus_feature labels across 30 declared machines. Each
label corresponds to a different settlement / attribution path through
`compute_trigger_sessions` + `RoundWinRule` dispatch.

#### §3.5.4 Trigger-session pattern reliance (`fresh_slotlab/trigger_sessions.py`)

Two trigger-session patterns implemented (per `trigger_sessions.py`
module docstring):

| Pattern | Trigger signal | Win-aggregation rule | Members |
|---|---|---|---|
| **Type 1** | `ReMarks.startswith("Trigger")` (Selector family) | last-non-None `WinCredits` | M12, M15, M90, M132, M206 (TopDollarSelector); M32 (QuickDollar); M6 (Fortunes); M39 (DancingDrum); M86 (HoppyHunting); M116, M210 (ChristmasSimple); M123 (Valentine) — **~12 underlying machines × 2-7 variants each** |
| **Type 2** | paid round with `WinCredits==0` + non-empty `PayoutIdToWinAmount` having win==0 keys, NOT `ReMarks="Trigger*"` | sum of non-None `WinCredits` | M273 + 84 WheelSelector variants; M201 / M209 / M257 (CommonSelector) — **~4 underlying × 4-85 variants** |
| **Neither** (no trigger sessions) | — | n/a | all 421 - (Type 1 + Type 2) = **the vast majority**, including the 64 F-Plain machines |

---

## §4 Cross-axis similarity matrix

Same-machine cluster IDs across all 5 axes for the representative
sample (brief §"Representative sample for rawdata"). "✓" = falls into
a large cluster; "*" = singleton/outlier on that axis.

| Machine | Axis 1 (SpinType) | Axis 2 (Feature) | Axis 3 (Paytable) | Axis 4 (Schema) | Axis 5 (Rules) |
|---|---|---|---|---|---|
| **M1** | ST-1A `{1}/{}` ✓ | F-Plain ✓ | 1-line, 3-reel ✓ | S-Base ✓ | none (default) |
| **M14** | ST-1A `{1}/{}` ✓ | F-Plain ✓ | 9-line, 3-reel ✓ | S-Base ✓ | none (default) |
| **M15** | ST-1L `{1}/{14,15}` ✓ | F-Selector ✓ | 2-line, 3-reel ✓ | S-TopDollar ✓ | `settlement_winamount` + Type 1 trigger |
| **M37** | ST-1A `{1}/{}` ✓ | F-Plain ✓ | 1-line, 3-reel ✓ | S-Base ✓ | reroll mechanic (in-spec, no rule) |
| **M31** | ST-1G `{43}/{44}` ✓ | F-FreeSpin ✓ | 7-line, 3-reel ✓ | S-Base ✓ | none (default; spec.json features=[FreeSpin]) |
| **M43** | ST-1M `{1}/{50,51}` ✓ | F-LockRespin+Minigame ✓ | 1-line, 3-reel ✓ | S-Base ✓ | none (default; spec.json features=[RespinAndMiniGame]) |
| **M99** | * `{96}/{97,98}` (singleton) | F-Wheel ✓ | 6-line, 3-reel ✓ | S-LockSym ✓ | `is_wild_nudge_round`? lock-related |
| **M120** | * `{1}/{138}` (singleton) | F-BCM+FS ✓ | 7-line, 3-reel ✓ | * RewardIdToCollectAmount (singleton extras) | `attribute_lines_to_pay_ids` suffix (109→9) |
| **M139** | ST-1A `{1}/{}` ✓ | F-Plain ✓ | 5-line, 3-reel ✓ | S-Base ✓ | `attribute_lines_to_pay_ids` suffix (55→5) |
| **M260** | * `{156}/{2,105,157}` (singleton) | F-BCM+FS+Wheel ✓ | 60-line, ?reel ✓ | * `{...,Buffs,NodeIndex,...}` 10-key singleton | needs `bcm_cycle_anchor` (not yet enabled) |
| **M268** | * `{140}/{125}` (singleton) | F-BCM ✓ | 5-line, 3-reel ✓ | * `{...,LockReels,SymbolIndexRatio,CreditsBySymbol}` singleton | needs `bcm_cycle_anchor` (per memory) |
| **M272** | ST-1E `{140}/{126}` ✓ | F-BCM+FS ✓ | 10-line, 3-reel ✓ | S-BCM-21k ✓ | none (default; presumably enabled later) |
| **M274** | * `{140}/{139}` (with M192) | F-BCM+Wheel ✓ | 6-line, 3-reel ✓ | S-BCM-21k ✓ | **`bcm_cycle_anchor`** ✓ |
| **M279** | * `{140}/{2,36}` (singleton) | F-BCM+MoveNudge+Wheel ✓ | 9-line, 3-reel ✓ | S-BCM-21k ✓ | `is_wild_nudge_round` ✓ + needs `bcm_cycle_anchor` |
| **M12$TopDollarSelector$0$** | n/a (no rawdata) | F-Selector ✓ | (inherits M12) | (inherits M12) | `settlement_winamount` ✓ |
| **M273$WheelSelector$0$** | n/a (no rawdata) | F-BCM+FS+Selector+Wheel ✓ | (inherits M273) | (inherits M273) | Type 2 trigger ✓ |
| **M201$CommonSelector$0$** | n/a (no rawdata) | F-FS+LockRespin+Selector ✓ | (inherits M201) | (inherits M201) | Type 2 trigger ✓ |
| **M21** | * `{27}/{25}` (singleton) | F-FS+Wheel ✓ | 4-line, 5-reel ✓ | * Buffalo/Deer/Eagle/Tiger/Wolf themed (singleton) | none — but bespoke fields ignored by analyzer |
| **M11** | * `{17}/{10,11,12}` (singleton) | F-FreeSpin ✓ | 9-line, 3-reel ✓ | * Diamond/heart fortune singleton | none |
| **M5** | * `{1}/{3,4}` (singleton) | F-FS+Selector ✓ | 31-line ✓ | + `{FreeSpinRatio, FreeSpinTimes, Ratio}` singleton | none |
| **M65** | * `{70}/{}` (singleton) | F-Plain ✓ | 28-line ✓ | * old-style collection singleton | none (rawdata anomaly: bonus rounds didn't surface in chunk_0001) |
| **M250** | * `{140}/{2,126}` (singleton) | F-BCM+FS+Wheel ✓ | 3-line, **20-reel** outlier | S-BCM-21k ✓ | needs `bcm_cycle_anchor` (100% fallback per memory) |

### §4.1 Co-cluster observations

1. **Axis 4 (schema) ↔ Axis 2 (feature)**: extras-`{AccCredits, CollectCount, CreditsSymbols, SymbolIndexToRewards}` correlates almost-perfectly with `{BCM, *}` feature tag. **28 schema-BCM machines all have `BCM` in feature tags**. Inverse not quite as tight: some F-BCM machines (M120, M65) emit different extras-shapes.

2. **Axis 1 (SpinType) ↔ Axis 2 (feature)**: weakly coupled. ST-1A (54 machines, paid=1 only) **all** map to F-Plain or F-FreeSpin (no machine in ST-1A is BCM or Selector). But ST-1B (paid=1, bonus=2) splits across F-Wheel and F-Selector. **Conclusion**: SpinType encodes feature presence/absence reliably, but not feature *type*.

3. **Axis 5 (rules) ↔ Axis 4 (schema)**: explicit rule reliance is **sparse** — only 13/421 declared, all in two narrow signatures (TopDollar S-TopDollar + M274 S-BCM-21k). But **implicit primitive reliance** (Bugs 1-4) tracks Axis 4 closely: every machine with `CollectCount` extra needs `detect_cycle_peak`, every machine with `ST=36` + `ReMarks="move"` needs `is_wild_nudge_round`.

4. **Axis 3 (paytable) ↔ everything else**: weakly correlated. F-Plain machines span 1-line to 9-line. F-BCM machines span 6-line to 60-line. No clean coupling.

5. **Variant explosion concentrates on Axis 5 patterns**: 166 variant rows derive from only 26 underlying machines. **All 166 variants share Axes 1-4 with their underlying** (the variant is a `Selector` parameterization that affects only how the trigger settles, not the paytable / rawdata schema). On Axis 5 they share the same rule_id with `applies_to` listing each variant explicitly.

6. **The "85-variant" outlier M273**: WheelSelector with 85 variants ($0$, $1$1-2-3, $1$1-2-4, …) — single Type-2 trigger pattern, single underlying paytable. Variant explosion is a **registry-level** concern, not an analyzer concern.

### §4.2 Same-cluster matrix (top-tier members)

Which machines co-cluster across ALL 5 axes simultaneously? A clean
"super-cluster" emerges only for the largest natural group:

| Super-cluster | Axes 1 / 2 / 3 / 4 / 5 | Members (rawdata-confirmed) | Total fleet est. |
|---|---|---|---|
| **SC-Vanilla** | ST-1A / F-Plain / 1-9 line / S-Base / no rules | M1, M14, M37, M101, M105, M127, M13, M135, M137, M139, M142, M143, M145 | ~45 (= the 45 machines with exact `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` logicClassNames) |
| **SC-BCM-Modern** | ST-1E or ST-1I or singleton (paid=140) / F-BCM+* / 6-10 line / S-BCM-21k / no rule (yet) | M147, M152, M153, M163, M186, M192, M194, M238, M250, M253, M263, M264, M265, M271, M272 | ~28 (matches S-BCM-21k count) |
| **SC-TopDollar** | ST-1L / F-Selector / 2-line / S-TopDollar / `settlement_winamount` + Type 1 trigger | M12, M15, M90, M132, M206 underlying + 12 variants | 17 (12 variants + 5 underlying, of which 1 is in rawdata directly) |
| **SC-WheelSelector** | (variants, mostly no rawdata) / F-BCM+FS+Selector+Wheel or F-Selector+Wheel / (inherits) / (inherits) / Type 2 trigger | M273 + 84 variants, M102 + 1, M187 + 1, M188 + 1, M198 + 1, M203 + 1, M204 + 1, M216 + 1, M219 + 1, M247 + 1, M261 + 1 | ~85+11 = 96 rows |
| **SC-LockRespin-50** | ST-1C / F-LockRespin / various lines / S-Base or S-LockSym / no rule | M150, M156, M159, M164, M177, M221, M223, M224 | ~9 |
| **SC-MoveNudge** | ST-1H / F-MoveNudge / various / S-Base / `is_wild_nudge_round` primitive (implicit) | M140, M149, M226, M26, M51 + M279 | ~6 |

The first super-cluster (**SC-Vanilla**) is the strongest natural seam.
After that the fleet fragments along Axis 4 extras.

---

## §5 Outlier inventory

Machines that do not fit any large cluster on at least one of the 5
axes. Each gets a one-line reason. Numbers reference §3 cluster IDs.

### §5.1 Heavy outliers (singletons on 3+ axes — bespoke per-machine code likely)

| Machine | Why outlier |
|---|---|
| **M21** | Buffalo theme — emits per-symbol counters `{Buffalo, Deer, Eagle, GoldenBuffalo, GoldenBuffaloIndexes, Tiger, TotalGoldenBuffalo, Wolf}` (Axis 4 singleton); 4-line 5-reel paytable; ST `{27}/{25}` singleton. |
| **M260** | Most-extended BCM schema (10 extras keys including `Buffs`, `NodeIndex`, `IncreasedCredits`) on Axis 4; **60-line** paytable (largest in fleet bar M113); 54 distinct pay_ids (largest); singleton ST `{156}/{2,105,157}`. |
| **M268** | Singleton extras `{...,LockReels,SymbolIndexRatio,CreditsBySymbol}`; CreditsSymbolRespin bonus_feature unique to this machine; per memory has 70-90% RTP in fallback bucket pre-`bcm_cycle_anchor`. |
| **M279** | Singleton ST `{140}/{2,36}`; F-BCM+MoveNudge+Wheel three-feature combo; "custom engine" per memory; needs `is_wild_nudge_round` + `attribute_lines_to_pay_ids` suffix + cycle peak handling all together. |
| **M274** | First machine to need explicit `bcm_cycle_anchor` rule; ST `{140}/{139}` shared only with M192; pid 5801 ListRewardWheel anchor unique. |
| **M113** | `ExpandedSymbols` extra (singleton); 81 distinct paylines (the most in fleet); 4-reel layout (rare). |
| **M11** | Diamond/heart fortune (singleton extras); ST `{17}/{10,11,12}` singleton with 3 bonus types. |
| **M250** | 20-reel grid (singleton); 3-line; 100% RTP leak into fallback bucket per memory until `bcm_cycle_anchor` enabled. |
| **M108** | Reel-collect fill-up mechanic (`FillUpTo`, `ReelCollect`); 31-line; singleton extras. |
| **M65** | Old-style explicit collection indexes (`CollectCollectionIndexes`, `ShowCollectionIndexes`, `TotalPrize`, `WinAmount`); 70 paid-ST; 28-line. |
| **M67** | `{ClosedIds, OpenedIds}` extras — open/close cell mechanic only here; 27-line. |
| **M120** | `RewardIdToCollectAmount` extras singleton; ST `{1}/{138}` singleton; needs suffix attribution (109→9). |

### §5.2 Medium outliers (singletons on 1-2 axes)

| Machine | Outlier dimension |
|---|---|
| **M99** | Lock-symbol respin family but paid-ST `{96}` makes ST-sig singleton; in S-LockSym cluster. |
| **M112** | ST `{1}/{97,98}` matches M99's bonus-pair but with paid=1 — singleton. |
| **M97** | Two paid ST `{87, 88}` (rare). |
| **M100** | `{CreditsBySymbol, LockReels}` extras (singleton). |
| **M107** | `{CollectCount, JackpotID, LastCollectCount, LockSymbols, PrevLockSymbols, TriggerCount}` — most-stacked lock+collection+jackpot combo. |
| **M122** | `{CurGameCount, SymbolIndexToFrameLevel}` — frame-level encoding singleton. |
| **M138** | `{AllWinIndexes, AllWinLines, CollectRatio, CollectedIndexes, CurWinIndexes, CurWinLines}` — all-ways-pay variant. |
| **M251 / M254** | Both emit `BuffTypes` extras (only 2 of fleet) but with different sub-shapes. |
| **M266** | Close cousin of M260's schema but without `Buffs`/`NodeIndex` — singleton. |
| **M276 / M256 / M259** | Three- and four-feature combos including MoveNudge (rare combo set). |
| **M226 / M231 / M244** | LockRespin + (MoveNudge | BCM+FreeSpin | BCM) singletons. |
| **M5** | `{FreeSpinRatio, FreeSpinTimes, Ratio}` — older FS-counter encoding singleton. |
| **M50** | `{AdditionalFreeSpinAmount, IsTriggerFreeSpin, RemainingFreeSpin, RewardMultiplier}` — older FS-counter encoding singleton. |
| **M93** | `{AddFreeSpins, AddReelGames, LockLines}` triple — F-FS+LockRespin+Wheel triple combo singleton. |
| **M24** | F-FS+Minigame combo singleton; pig/gold themed extras. |
| **M22** | `{DoubleSymbolReward}` singleton extras; F-FreeSpin. |
| **M18** | `{JackpotIds, TntReels}` — TNT theme singleton. |
| **M20** | `{JackpotIds, LockLines}` — combo singleton. |
| **M27** / **M33** / **M36** | All in S-AddFS extras cluster but with different sub-shapes. |
| **M76** | `{BonusDiamondGoal, DiamondLives, DiamondsCollectedAmount}` singleton. |
| **M98** | `{AccumulatedCredits, CoinsRemaining, TotalCoins}` singleton. |
| **M119** | `{AccAmount, Multiplier}` singleton. |
| **M121** | `{Level}` singleton. |
| **M130** | `{AccAmount}` singleton. |

### §5.3 Variant-explosion outliers (registry-level, not analyzer-level)

| Underlying | Variant count | Why outlier |
|---|---|---|
| **M273** | 85 variants | Single Type-2 WheelSelector with combinatorial parameterization. All variants share Axes 1-4. |
| **M201** | 8 variants | CommonSelector — generic 3-of-N selector. |
| **M123** | 7 variants | ValentineSimpleSelector — three-pick. |
| **M39 / M86** | 5 variants each | Themed selectors. |
| **M209 / M257** | 4 variants each | CommonSelector instances. |

These are **not analyzer-side outliers** — they all share rules and
schema with their underlying. They concern the registry and the
md5-fanout path (per memory `project_variants_fleet.md`).

### §5.4 Counting outliers

| Category | Count |
|---|---|
| Heavy outliers (§5.1, singletons on 3+ axes) | 12 |
| Medium outliers (§5.2, singletons on 1-2 axes) | ~30 |
| Variant-explosion underlyings (§5.3) | 26 |
| **Total fleet items needing per-machine code consideration** | **~42** (12 heavy + 30 medium, ignoring variants) |

That leaves **~213 of 255 non-variant machines (84%)** that cluster
cleanly into the six super-clusters of §4.2.

---

## §6 Suggested groupings for plugin architecture

> **Descriptive only** — these are the natural seams the data reveals.
> The arch-designer decides how to express them as plugins, base
> classes, manifests, or hash composition. The taxonomist's job is
> only to surface them.

### §6.1 The four-tier shape

Data suggests four shells from inside-out, each describing a wider
group of machines:

1. **Tier-0 (base envelope)** — the 17-key `roundResult` shape:
   `{BetAmount, CostCredits, CurJackpotStoreWin, IsLackCreditsSpin,
   LastCredits, PayLineGroupId, PayoutByPayline, PayoutGroupId,
   PayoutIdToWinAmount, RTPId, ReMarks, ReelSkin, RewardLastNode,
   SpinTimes, SpinType, StopSymbolsByCol, WinCredits}`. **All 421
   machines** emit at least these keys. The analyzer's default
   `extract_round_win` / `extract_round_payouts` / paid-round
   classification work off this tier alone.

2. **Tier-1 (vanilla mechanism)** — **~45 SC-Vanilla machines** (M1,
   M14, M37, M101, M139, …) that emit ONLY Tier-0 keys, declare ONLY
   `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}`
   logic classes, and have NO rule entries. These are pure paytable
   variations.

3. **Tier-2 (single-feature archetype)** — clusters of machines sharing
   one bonus mechanism each:
   - **2a "Wheel-on-ST=2"** (~10 machines, ST-1B): F-Wheel.
   - **2b "Freespin-on-ST=126"** (~8 machines, ST-1D).
   - **2c "Freespin-on-ST=50"** (~9 machines, ST-1C, LockRespin
     variant).
   - **2d "LockSymbol"** (~5 machines, S-LockSym extras).
   - **2e "LockLines"** (~5 machines, S-LockLines extras).
   - **2f "TopDollarSelector"** (12-17 machines incl. variants, SC-TopDollar).
   - **2g "WheelSelector"** (~96 rows incl. variants, SC-WheelSelector).
   - **2h "MoveNudge"** (~6 machines).
   - **2i "Minigame trigger"** (M43, M44, M54, M75 + ~5 others).
   Each tier-2 archetype has **a shared trigger signal + a shared
   settlement rule**. The TopDollar archetype already has its rule
   (`settlement_winamount`); WheelSelector has its Type-2
   trigger-session pattern. Others currently rely on the legacy default
   path.

4. **Tier-3 (multi-feature stack)** — machines combining two or more
   tier-2 archetypes. ~30 machines fit here, including the most-cited
   "outliers" in memory:
   - **M279**: BCM cycle + MoveNudge + Wheel (3 stacked).
   - **M260**: BCM cycle + FreeSpin + Wheel + multi-pool credits.
   - **M274**: BCM cycle + ListRewardWheel.
   - **M268**: BCM cycle + CreditsSymbolRespin + LockReels.
   - **M250**: BCM cycle + FreeSpin + Wheel on a 20-reel grid.

5. **Tier-4 (bespoke / theme)** — true singletons (§5.1 heavy
   outliers). M21 (Buffalo), M11 (Diamond/heart fortune), M113
   (ExpandedSymbols), M120 (RewardIdToCollect), M65 (old collection
   format), M67 (open/close cells), M76 (Diamond bonus), M97 (Pond),
   M98 (Coin-bank), M251/M254 (BuffTypes), M260, etc.

### §6.2 Cross-axis-aligned plugin seams

Where the same set of machines co-cluster across 3+ axes, that's a
natural plugin boundary:

| Plugin candidate | Co-cluster across axes | Member count | Mechanism captured |
|---|---|---|---|
| **plugin-vanilla-paytable** | A1 (ST-1A) ∩ A2 (F-Plain) ∩ A4 (S-Base) ∩ A5 (no rules) | ~45 | Pure 1-9 line paytable, default trigger/settle |
| **plugin-topdollar-selector** | A1 (ST-1L) ∩ A2 (F-Selector) ∩ A4 (S-TopDollar) ∩ A5 (`settlement_winamount` + Type-1 trigger) | 5 underlying + 12 variants = 17 rows | TopDollar settlement |
| **plugin-bcm-cycle** | A2 (F-BCM*) ∩ A4 (S-BCM-21k) ∩ A5 (needs `bcm_cycle_anchor` + `detect_cycle_peak`) | ~28 schema-confirmed; 30 by bcm_pairings | BCM cycle anchor + peak detection |
| **plugin-wild-nudge** | A1 (ST-1H or contains ST=36) ∩ A4 (ReMarks="move" present) ∩ A5 (`is_wild_nudge_round`) | ~7 confirmed (memory cites 25 (m,mode) pairs) | Nudge round transparency |
| **plugin-pay-id-suffix-attribution** | A3 (symbol_id != pay_id) ∩ A5 (`attribute_lines_to_pay_ids` Pass 2-3) | 4 confirmed (M120, M123, M139, M279); fleet-wide audit needed | Suffix and single-remaining attribution |
| **plugin-wheel-selector-type2** | A2 (Selector+Wheel) ∩ A5 (Type-2 trigger) | M273 (85 variants) + others = ~96 rows | Type-2 (sum-all) session-win aggregation |
| **plugin-common-selector-type2** | A2 (Selector but generic) ∩ A5 (Type-2) | M201, M209, M257 + variants = ~20 rows | Same Type-2 path with different trigger marker |
| **plugin-lock-symbol** | A4 (S-LockSym) ∩ A2 (LockRespin) | 5 (M103, M104, M99, M240, etc.) | PrevLockSymbols carry-over |
| **plugin-lock-lines** | A4 (S-LockLines) ∩ A2 (LockRespin) | 5 (M10, M131, M133, M23, M241) | LockLines carry-over |

### §6.3 What does NOT cluster cleanly

These signals fragment too much to be plugin-ready:

- **Single-machine theme counters** (M21 Buffalo, M11 Diamond, M76
  Diamond goal, M98 Coin-bank, M97 Pond): each is a unique extras-set.
  Suggest per-machine plugin OR an "ignored extras" plugin that flags
  them as informational-only.
- **Older AddFreeSpin encoding** (M27, M33, M36, M5, M50): scattered
  extras shapes. Could be unified as a "legacy-freespin-counter" plugin,
  but only 5-6 machines benefit.
- **The 60+ Plain-with-bonus-token machines** (ST-1B/C/D/E split):
  bonus token is in `SpinType` only, with no extras signal. Plugin
  boundary here would have to be drawn on Axis 1 alone, which is too
  thin.

### §6.4 Suggested manifest schema dimensions (descriptive)

Per-machine manifest could declare reliance on any of these axes-cross-product:

```
machine_id: <str>
schema_tier: vanilla | bcm-21k | topdollar | locksym | locklines | bespoke-<X>
spin_type_convention: <paid_st_set>/<bonus_st_set>
feature_tags: subset of {Plain, FreeSpin, LockRespin, Wheel, BCM, Selector, MoveNudge, Minigame}
round_win_rules: [list of rule_id from RULE_REGISTRY]
classification_primitives: [list of {is_wild_nudge_round, detect_cycle_peak, attribute_lines_to_pay_ids_suffix, ...}]
selector_type: TopDollarSelector | WheelSelector | CommonSelector | ... | null
bcm_target_feature: NewFreespin | Wheel | LockReSpin | ListRewardWheel | ... | null
trigger_session_pattern: type_1 | type_2 | null
```

The hash composition (per brief §6) could then be:
`hash(machine) = hash(base) + hash(schema_tier) + hash(sorted(feature_tags)) + hash(sorted(round_win_rules)) + hash(sorted(classification_primitives))`,
with adding a new feature plugin invalidating only machines listing it.

### §6.5 Calibration: how much of the fleet is "shared"

Conservative estimate of blast-radius reduction available:

| Touch target | Today's blast | If per-tier-2 plugin | If per-tier-3 plugin |
|---|---|---|---|
| Add `'scatter'` symbol kind to core engine | 421 (current commit 54b7d01) | ~45 SC-Vanilla unaffected; ~10 SC-Selector affected; ~28 BCM affected; … | same as middle column |
| Add `payouts_by_spin_type` (8411c9d) | 421 | All Tier-1+ would still see (it's analyzer-output, not engine) | same |
| Change ST=14 phantom-filter threshold | 421 | Only SC-TopDollar (17 rows) | Only SC-TopDollar |
| Add new BCM `_unattributed_st` cleanup rule | 421 | Only S-BCM-21k (28 rows) | Only the affected sub-clusters |
| Theme-specific tweak on M21 Buffalo extras | 421 | 1 (M21 only, plugin-bespoke) | 1 |

The taxonomy supports a ~10× reduction in blast radius for most kinds
of changes if Tier-2 and Tier-3 plugin lines are drawn along the
co-clusters identified in §6.2.

---

*End of taxonomy. arch-designer should treat §6.2 and §6.4 as a menu
of plugin-boundary candidates, not a prescription. The 12 heavy
outliers in §5.1 deserve named carve-outs in whatever the designer
proposes — they are not going to fit any clean cluster.*
