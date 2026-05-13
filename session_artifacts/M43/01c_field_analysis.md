# Stage 1c — M43 mechanism inference from rawdata + logicClassNames

## Verdict (one-liner)

**partial-pass** — reels, paytable structure, pay_id→symbol mapping, SpinType semantics, respin trigger, mini-game characterization all confirmed at HIGH confidence; **wild substitution exact rules** (specifically pay_id 8 semantics and the precise `blankup`/`blankdown` adjacency-marker mechanism) are MED confidence; **respin trigger rule** (which winning combos qualify for a respin) is LOW confidence — only ~10% of base-paid wins trigger respin and I cannot infer the discriminator from rawdata alone. Designer at Stage 4 should flag wild & respin rules for user clarification or production paytable cross-check before Stage 6.

---

## Inputs

- `rawdata/M43/mode_1/` — 41 chunks, 650,000 paid spins
- `configs/machines.json` M43 entry → `logicClassNames`:
  ```
  M43WinMiniGameGenerator
  NormalRTPPreProcessor
  NormalSpinGenerator
  WinNormalSpinPostProcessor
  WinReSpinGenerator
  WinReSpinPostProcessor
  WinReSpinPreProcessor
  WinRespinWildValidator
  WinWildValidator
  ```
- SESSION_BRIEF archetype hint: **Lucky Ducky** (IGT 3-reel classic)
- user_brief: confirms 3-reel single-line, mode-1-first, current bucket distribution "稀烂"
- **No production paytable doc supplied** — all rules below are reverse-engineered.

---

## §1 Reel structure

| property | value | source | confidence |
|---|---|---|---|
| reel count | **3** | StopSymbolsByCol length | HIGH |
| visible rows per reel (window) | **3** (top / mid / bot) | StopSymbolsByCol element format `'sym1-sym2-sym3-'` | HIGH |
| payline count | **1** (mid-row only) | PayoutByPayline always starts with `'1:'`, no other line ID observed | HIGH |
| strip layout (symbol sequence) per reel | identical 14-triple inventory on R1 = R2 = R3 (same 16-stop strip) | Euler walk over 14 distinct triples per reel | HIGH |
| stop weights per reel | **DIFFERENT per reel** — same physical strip, different per-stop weighting | mid-row marginal `wild` is 0.15% on R1 vs 1.84% on R2 vs 0.18% on R3 (~12× concentration on R2) | HIGH |
| physical strip length | **16 stops** (inferred via Euler walk) | 14 distinct triples + 2 duplicate transitions at `(1bar,blank,_)` and `(blank,1bar,_)` | MED (16 is one of multiple consistent recoveries) |

### Reconstructed strip (Euler walk over chunk_0001 triples)

```
[1bar, blank, 1bar, blank, 7, blank, 3bar, blank, 2bar, blank, 1bar, blankdown, wild, blankup, 7, blank]
```

Symbol multiplicity per strip:
- `blank`: 7 stops
- `1bar`: 3 stops
- `7`: 2 stops
- `2bar`: 1 stop
- `3bar`: 1 stop
- `wild`: 1 stop (flanked by `blankup` above + `blankdown` below)
- `blankup`: 1 stop (only at the position immediately above wild)
- `blankdown`: 1 stop (only at the position immediately below wild)

**Wild's neighbors are physically distinguished** as `blankup`/`blankdown` rather than plain `blank` — this lets the engine tell "blank near wild" apart from "ordinary blank" and award `pay_id=9` (the 2x small consolation) when a `blankup`/`blankdown` lands on the payline. This is the classic Lucky Ducky / 1-line-3-reel pattern.

Confidence: **HIGH** for layout structure (3 reels × 3-row window × 1 payline); **MED** for the exact 16-stop strip recovery (multiple Euler walks fit the same observation).

---

## §2 Symbol vocabulary

| symbol | role | observed on |
|---|---|---|
| `7` | top-paying base symbol | all 3 reels |
| `wild` | wild substitute + own pay | all 3 reels |
| `3bar` | mid-pay symbol | all 3 reels |
| `2bar` | mid-pay symbol | all 3 reels |
| `1bar` | low-pay symbol | all 3 reels |
| `blank` | true blank (non-paying) | all 3 reels |
| `blankup` | "blank above wild" marker (adjacent-blank marker) | all 3 reels |
| `blankdown` | "blank below wild" marker (adjacent-blank marker) | all 3 reels |

8 symbols total. `blankup`/`blankdown` are **physically distinct stops** in the strip but visually look like blanks; their only purpose is to mark "wild is one row away" so that the engine can pay the 2x small consolation (`pay_id=9`) when one lands on the payline.

Confidence: **HIGH** — symbol vocabulary is direct enumeration over 650k spins.

---

## §3 Paytable (pay_id → symbol mapping)

Reverse-engineered from rawdata over all 650k spins. Base win amounts are at bet=1000.

| pay_id | family | base win | base multiplier | doubled multiplier | combo description |
|---|---|---|---|---|---|
| **2** | wild_top | 80,000 | **80×** | 160× (1 bonus wild) | 3× wild on payline (top jackpot) |
| **3** | seven_top | 60,000 | **60×** | 120× | 3× 7 on payline (wild substitutes for 7) |
| **4** | bar3_top | 40,000 | **40×** | 80× | 3× 3bar on payline (wild substitutes) |
| **5** | bar2 | 20,000 | **20×** | 40× | 3× 2bar on payline (wild substitutes) |
| **6** | bar1 | 10,000 | **10×** | 20× | 3× 1bar on payline (wild substitutes) |
| **7** | bar_mixed | 5,000 | **5×** | 10× | any 3 bars (1/2/3 mixed) on payline |
| **8** | wild_blank_special | 5,000 | **5×** | 10× or 20× | wild + blank-flank pattern (rule ambiguous, see below) |
| **9** | small_consol | 2,000 | **2×** | 4× | any `wild`/`blankup`/`blankdown` on payline mid-cell |

### Win-doubling rule

When the winning payline contains an extra `wild` stop (or `blankup`/`blankdown` marker pointing to a wild on an adjacent row), the win is doubled. Examples from 650k:
- pay_id=6 (`1bar,1bar,1bar`) wins 10,000 base. With one extra wild in the window (e.g. `1bar, blankdown, 1bar` where R2 has a wild on top row), wins 20,000.
- pay_id=4 (`3bar,3bar,3bar`) base 40,000; doubled 80,000 observed (small sample, 1/3 of pay_id=4 hits).
- pay_id=9 base 2,000; doubled to 4,000 when the wild is on R2 mid-row (vs. only blankup/blankdown adjacent).

This is the classic "wild as 2× multiplier" rule.

Confidence: **HIGH** for the 8 pay_ids (2→9) and their base multipliers; **MED** for the exact doubling-trigger rule (it correlates with wild on/near payline but I haven't ruled out a more general N-wild → 2^N multiplier).

### Ambiguity flag — pay_id=8

Pay_id=8 (912 hits in 650k, avg 7.4× bet) is observed with mid-row patterns like `(blank, blankup, blankdown)`, `(blank, blankdown, blankup)`, `(blank, blank, blankdown)` — i.e. the payline has blanks/markers, and the **adjacent rows** (top/bot) carry 7s or wilds. This pattern suggests pay_id=8 may be:

- (a) a "near 3× 7" pay (3 sevens visible across the 3-row window but not all on the payline)
- (b) a "2 wilds + 1 blank" special pay (1.5x the 5x pay)
- (c) a derivative wild-combo pay that bridges the bar pays and the seven_top

Designer should escalate user at Stage 4 to clarify rule; the rawdata shows this pay exists at 5x base but the trigger logic is not unambiguous. Confidence: **MED** family label; **LOW** exact rule.

Confidence overall on §3: **HIGH** for the top 7 pay_ids cadence + base multiplier; **MED** for pay_id=8 exact rule; **MED** for pay_id=2 RTP estimate (only 14 hits in 650k → wide CI ~±50% relative on the 0.31 pp contribution; cadence "1 in 46k" is HIGH).

### Structural observation re: user's '稀烂' critique

The paytable's apex base multiplier observed is **80× (pay_id=2, 3× wild)**, doubled to **160× with a bonus wild via the observed multiplier mechanism**. No on-reel pay across 650k spins reached ≥200×. The only RTP component currently delivering large multipliers is the mini-game (avg 27.2× bet, with observed individual tokens reaching higher). This is an **observation**, not a prescription — Stage 4 Designer will evaluate which mechanisms (per-reel weight shift / mini-game token rebalance / wild multiplier rule clarification) can move bucket weight toward the high end while respecting the paytable-immutability invariant (§1.1).

---

## §4 Wild behavior

### Standard substitution
`wild` on the payline substitutes for any of: `7`, `1bar`, `2bar`, `3bar`. Examples observed across 650k:

- `mid = (2bar, wild, 1bar)` paid pay_id=7 (mixed bars) — wild filled middle position as a generic bar
- `mid = (wild, blank, 1bar)` paid pay_id=9 (small consol) — wild alone counts as 2× consolation
- `mid = (7, blankup, blankdown)` paid pay_id=3 (3× 7) — `blankup`/`blankdown` markers indicate wilds adjacent that substitute as 7s

### Wild multiplier behavior
- `WinWildValidator` (logic class) confirms the wild has validator-side logic during base spin
- `WinRespinWildValidator` confirms wild validation is also applied to the **respin** result
- Wild count drives the multiplier: 1 wild → 2×; observed but not exhaustively verified for 2-wild → 4× or 3-wild → 8×

Confidence: **HIGH** for substitution; **MED** for exact multiplier rule (need explicit pay sheet to confirm whether stack scaling is multiplicative or capped).

---

## §5 Respin mechanic (SpinType=50)

| property | value | source | confidence |
|---|---|---|---|
| ReMarks marker | `'ReSpin'` | observed string | HIGH |
| CostCredits | **0** (free) | respin rounds | HIGH |
| ReelSkin | typically **6** (vs 1 for base) | respin rounds | HIGH |
| trigger rate | **1.32%** of paid rounds | 650k cross | HIGH |
| chain length | 1 (mostly), rarely 2 | observed | HIGH |
| win rate of respins | **27.7%** | 8820 respin rounds, ~2444 winning | HIGH |
| trigger rule | **NOT every base-spin win triggers respin** | only 1.3% of paid rounds → respin; base win rate is 13.3% | (see ambiguity) |

### Trigger ambiguity (LOW confidence on exact rule)

Respins follow only ~10% of base-spin wins (134 / 1314 in chunk_0001 sample, scaled to ~1300 / ~13000 across 650k). The discriminator is **not visible** in the stop pattern alone. Possible rules:

- (a) Triggered only when a winning combo includes a specific wild-adjacent pattern (e.g. `blankup`/`blankdown` marker on payline + a paying win)
- (b) Triggered probabilistically (e.g. 10% of all wins regardless of pattern)
- (c) Triggered by a specific pay_id threshold (e.g. pay_id 2-5 only) — partially supported by observation (need to verify)

`WinReSpinGenerator` / `WinReSpinPreProcessor` / `WinReSpinPostProcessor` confirm respin has its own pre+post processing, but the precise trigger predicate is opaque from rawdata. Designer should ask user / paytable doc to verify.

Confidence: **HIGH** on the respin existence + free-cost mechanic; **LOW** on the trigger discriminator.

---

## §6 Win mini-game (SpinType=51) — `M43WinMiniGameGenerator`

| property | value | source | confidence |
|---|---|---|---|
| ReMarks marker | `MiniGame[N]` or `MiniGame[N,M,K,...]` | observed | HIGH |
| Token range | **101 - 110** (10 distinct tokens) | observed | HIGH |
| Single-token frequency vs multi-token | majority single (e.g. `MiniGame[108]`); minority multi (e.g. `MiniGame[103,109]`) | observed | HIGH |
| CostCredits / BetAmount / StopSymbolsByCol | **fields missing entirely** from mini-game rounds (7-key reduced keyset) | observed | HIGH |
| trigger rate | **1.05%** of paid rounds spawn mini-game | 650k cross | HIGH |
| total mini-game rounds | 6,847 | 650k cross | HIGH |
| avg win | **27.2× bet** | observed | HIGH |
| RTP contribution | **28.65 RTP pp** (out of 93.23% total) | sanity check | HIGH |
| trigger predicate | **NOT visible in preceding round** | preceding round can be win or no-win, normal or respin | HIGH |

### Token semantics

Tokens 101-110 (10 distinct) likely represent **mini-game prize tiers**. The multi-token notation (`MiniGame[103,109]`, etc.) suggests the mini-game **internally accumulates multiple prizes** in one event. Token frequency distribution from 650k:

| token | count | inferred role |
|---|---|---|
| 108 | 2,051 | top-frequency tier (low/mid prize?) |
| 109 | 2,044 | mid-frequency |
| 110 | 1,955 | mid-frequency |
| 102 | 1,376 | |
| 101 | 1,365 | |
| 103 | 1,014 | |
| 105 | 970 | |
| 104 | 961 | |
| 107 | 792 | |
| 106 | 771 | |

The win range is wide (avg 27× bet) and the mini-game contributes the second-largest slice of RTP (after the bar1 family at 31% share). This is structurally why M43 hits its 93% RTP even though the on-reel paytable only delivers ~64.6 pp — the mini-game adds the remaining ~28.6 pp.

### Trigger predicate ambiguity

Mini-game trigger is independent of round outcome. Looking at the 6,847 mini-game cases:
- 95% follow a paid round with no win
- 22% follow a paid round with a win
- 1 case follows a respin

`M43WinMiniGameGenerator` is a **machine-specific generator** (not in shared library), confirming bespoke trigger logic. Confidence: **HIGH** on the cadence/contribution; **LOW** on the exact trigger probability/condition; designer must verify with user or production rule sheet.

Confidence overall: **HIGH** for what the mini-game does and how often; **LOW** for the trigger predicate.

---

## §7 SpinType semantics

| SpinType | name | observed count (650k) | rounds with stops? | role |
|---|---|---|---|---|
| **1** | normal paid spin | 650,000 | YES | base spin (charge bet, evaluate reels) |
| **50** | respin | 8,820 | YES | free respin after qualifying win |
| **51** | mini-game | 6,847 | NO (no stops) | bonus mini-game event |

`SpinTimes` field **does not increment** for SpinType=50 or 51 — they share the SpinTimes index of the triggering base round, confirming respin and mini-game are **attached to the triggering paid round** (session-centric semantics per `memory/feedback_session_semantics.md`).

Confidence: **HIGH**.

---

## §8 Round structure / envelope

### Per-round fields (SpinType=1 paid base spin) — 17 fields

```
BetAmount, CostCredits, CurJackpotStoreWin, IsLackCreditsSpin, LastCredits,
PayLineGroupId, PayoutByPayline, PayoutGroupId, PayoutIdToWinAmount,
RTPId, ReMarks, ReelSkin, RewardLastNode, SpinTimes, SpinType,
StopSymbolsByCol, WinCredits
```

### Per-round fields (SpinType=51 mini-game) — 7 fields

```
IsLackCreditsSpin, LastCredits, RTPId, ReMarks, SpinTimes, SpinType, WinCredits
```

### Per-round fields (SpinType=50 respin) — same 17 fields as paid spin

Respins are full reel events, just with `CostCredits=0` and `ReMarks='ReSpin'`.

### Notable field semantics

- `PayoutByPayline`: format `'1:X-Y(p1,p2,p3,);  '` where X-Y is pay_id-pay_id (always X==Y for M43), and (p1,p2,p3,) is **the reel-stop-index per reel** for the winning position (used for visual reel positioning).
- `RewardLastNode`: list of `'P-'` tokens where P is the winning pay_id (e.g. `['7-']` for pay_id 7). Used as a sanity / display layer.
- `PayoutIdToWinAmount`: `{pay_id_str: win_credits}` — the canonical win attribution per pay_id (sum equals `WinCredits` for base+respin rounds).
- `CurJackpotStoreWin`: always 0 in observed data — likely unused for M43 (per `memory/reference_upstream_unmined_fields.md` mining).

Confidence: **HIGH**.

---

## §9 Mapping to `logicClassNames`

| Logic class | role in this machine (inferred) | confidence |
|---|---|---|
| `NormalRTPPreProcessor` | pre-spin RTP gating / bet validation | HIGH |
| `NormalSpinGenerator` | base spin reel-stop selection (weighted strip sampling) | HIGH |
| `WinNormalSpinPostProcessor` | base spin payline evaluation + wild multiplier | HIGH |
| `WinWildValidator` | validates wild substitution on base spin | HIGH |
| `WinReSpinPreProcessor` | decides whether to trigger a respin (the opaque predicate from §5) | HIGH |
| `WinReSpinGenerator` | respin reel-stop selection (potentially different weighting) | HIGH |
| `WinReSpinPostProcessor` | respin payline evaluation (same rules as base + possibly cumulative multiplier) | HIGH |
| `WinRespinWildValidator` | validates wild substitution on respin | HIGH |
| `M43WinMiniGameGenerator` | mini-game event spawning + prize-tier sampling (independent of reels) | HIGH |

Mapping is unambiguous via SpinType + ReMarks + observed field set. Confidence: **HIGH**.

---

## §10 What is still ambiguous (Designer must verify at Stage 4)

| ambiguity | priority | likely impact |
|---|---|---|
| **Respin trigger predicate** (which winning combos qualify) | **HIGH** | affects respin RTP attribution and Stage 6 tune — without this, virtual respin generator could be either too generous or too stingy |
| **Pay_id=8 exact rule** (912 hits, 5× base) | MED | mid-bucket RTP contribution; partial 7s vs wild-blank-special vs other |
| **Wild multiplier stacking** (1 wild → 2×; 2 wilds → 4× or capped?) | MED | affects high-multiplier bucket share (the user's '稀烂' complaint area) |
| **Mini-game trigger predicate** (random? state-dependent?) | MED | mini-game contributes 28.6 RTP pp; trigger predicate determines whether mini-game can be re-shaped via reel design or only via M43WinMiniGameGenerator logic |
| **Mini-game token-tier prize structure** (what each token 101-110 pays) | LOW | already aggregated into one 27.2× avg; finer detail only matters for player narrative |
| **CurJackpotStoreWin field role** | LOW | observed always 0; likely vestigial for M43 |

Recommended Stage 4 escalation: **ask user or fetch production paytable doc to disambiguate respin trigger predicate** before Stage 5 verify.py is written. The other items can be deferred to Stage 6 empirical fit.

Confidence: items are flagged HIGH/MED/LOW per impact, not per uncertainty.

---

## §11 Cross-check against archetype hint (Lucky Ducky)

User stated archetype = Lucky Ducky (IGT 3-reel classic). Observations consistent with this archetype:

- **3-reel 1-line single-payline** ✓
- **Bar family** (1/2/3) ✓
- **Top symbol = 7** ✓ (matches Lucky Ducky's "7" or themed top)
- **Wild substitution + 2× multiplier** ✓
- **Small-win consolation** ✓ (the `wild + blank-flank = 2×` pay_id 9 pattern is classic Lucky Ducky pull-tab consolation behavior)
- **No scatter, no free-spin** ✓ (mini-game replaces free-spin role)
- **`blankup`/`blankdown` marker stops** — this is the **Lucky Ducky-specific signature**: physical adjacency markers around wild that pay 2× on the payline. R's archetype research (Stage 1d, parallel) should confirm whether this matches the published Lucky Ducky strip layout.
- **R2 wild concentration** — wild lands on the R2 mid-row ~12× more often than on R1/R3 mid-rows (1.84% vs 0.15%/0.18%). This is implemented as **per-reel weighting** (same strip vocab, different stop weights), not via different strips. This pattern mirrors the published Lucky Ducky/Lucky Lemmings layout where wilds cluster on the middle reel for "near-hit" visibility.

Confidence on archetype match: **HIGH** structural fit; **MED** for exact-paytable match (no published Lucky Ducky paytable doc in hand).

---

## §12 Summary verdict

- **§1-§3 (reels, vocab, paytable)**: HIGH confidence, ready for Stage 2 engine implementation.
- **§4 (wild)**: HIGH for substitution, MED for exact multiplier rule. Designer can write a 2× multiplier rule as initial implementation and revisit at Stage 6 if RTP mismatch arises.
- **§5 (respin)**: HIGH on existence, LOW on trigger rule — **must escalate user before Stage 5**.
- **§6 (mini-game)**: HIGH on cadence + contribution, LOW on trigger predicate — defer to Stage 6 tune.
- **§7-§9 (SpinType, envelope, logic classes)**: HIGH confidence.
- **§10 (open ambiguities)**: listed for Designer triage.

**Overall**: mechanism inference is sufficient to start Stage 2 (engine implementation) on the **base spin + paytable** with HIGH confidence; **respin trigger** and **mini-game trigger** need user clarification or paytable doc reference before Stage 5/6 close. The user's "稀烂" critique in user_brief is fully visible in §1b §2 (high-multiplier buckets are thin — ge100_lt200 = 0.0043% rate, ge200_lt500 = 0.0005% rate, and ge500/ge1000/ge5000 = 0 hits in 650k); the structural cause is the paytable being dominated by 3 mid pays (bar1, bar_mixed, small_consol) + a mini-game that is a separate logic class.

---

## Sources

- Rawdata: `rawdata/M43/mode_1/chunk_0001.json` … `chunk_0041.json` (650k paid spins)
- Registry: `configs/machines.json` lines 9966-9989 (M43 entry + logicClassNames)
- Per `memory/feedback_no_hardcode.md`: all semantics inferred per-machine from this rawdata; not borrowed from M14/M15.
- Per `memory/feedback_session_semantics.md`: respin / mini-game wins attribute to the triggering paid round throughout.
- Per `memory/feedback_capture_drift.md`: any structural drift (new SpinType / new logic class / new ReMarks) on future re-fetch must raise an explicit error in baseline_dump.py.
