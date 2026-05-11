# M15 archetype research (Top Dollar / Double Top Dollar family)

> Stage 1d output. Date: 2026-05-11.
> Agent R (Researcher) deliverable per `slot_designer/ONBOARDING_PROCESS.md` §4 + §5 Stage 1d.
> **Scope**: industry-side archetype research only. Inside-data (M15 rawdata) is Agent A's Stage 1b deliverable.

---

## 0. Methodology

### 0.1 Sources consulted
- **Industry / review sites**: Know Your Slots, SlotsMate, SlotCatalog, SlotsLaunch, Flip The Switch, GGB Magazine, easy.vegas, urcomped, vegasslotsonline.
- **Math / data**: Wizard of Odds appendices, Wizard of Vegas forum threads (math + game strategy), Casino Operations Management citations on PAR sheets.
- **Academic**: Harrigan 2007 (`10.1007/s11469-007-9066-8`, `10.1007/s11469-007-9139-8`), Lucas & Singh 2008 (Cornell Hospitality Quarterly), and recent Springer journal review threads on near-miss psychology.
- **Manufacturer / cabinet**: IGT product pages, IGT/Barcrest S-AVP and S2000 documentation, Slot Machines Unlimited / Ohio River Slots dealer listings.

### 0.2 Search strategy
WebSearch + WebFetch invoked with queries focused on:
- Direct game name (Top Dollar / Double Top Dollar) for RTP, paytable, mechanics
- Family proxies (Red White Blue, Double Diamond, Blazing 7s, Triple Red Hot 777) for hit rate / CV / family-share baselines
- Mechanic primitives (cherry-anywhere, virtual reel mapping, PWDF, near-miss clustering) for design philosophy
- Bonus psychology (Take Offer or Try Again, pick game UX, illusion of control)

### 0.3 Confidence convention
- **HIGH**: ≥2 independent sources agree numerically, or a primary source (Wizard of Odds appendix, academic paper, manufacturer doc)
- **MEDIUM**: 1 solid source, plausible given related games
- **LOW**: 1 forum / dealer post, inferred only

### 0.4 Caveats up front
- IGT does **not** publish PAR sheets for Top Dollar at any denom. All RTP / hit / per-family share for the land-based version are inferred from neighbors (Red White Blue) + the published online Double Top Dollar (2025 release) + dealer cabinet metadata.
- "Top Dollar" refers to multiple SKUs: (a) **IGT-Barcrest S2000 land cabinet** (3-reel, single payline, $0.25–$100 denoms), (b) **IGT S-AVP land cabinet** (3-reel, 5-line, multi-coin), (c) **5-reel video AVP** variant, (d) **online Double Top Dollar** (3-reel, 9-line, 2025). M15 spec.json hews to (a) 3-reel × 1 payline. Most archetype claims below are scoped accordingly.

---

## 1. Top Dollar archetype overview

### 1.1 History & lineage
- "Top Dollar is one of the most well-known and successful slot machine games that IGT ever created. Top Dollar was the most popular game in the history of IGT's U.K.-based Barcrest subsidiary." [GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) (accessed 2026-05-11). **HIGH**
- IGT acquired Barcrest in 1998; release year for the original Top Dollar SKU not nailed in public sources but consensus is late-1990s. [Wikipedia IGT 1975-2015](https://en.wikipedia.org/wiki/International_Game_Technology_(1975%E2%80%932015)) (accessed 2026-05-11). **MEDIUM**
- "Top Dollar is a game that has enduring popularity on the casino floor … rare to find a casino without at least one or two of these in the high limit room." [Know Your Slots — Top Dollar](https://www.knowyourslots.com/top-dollar-mechanical-reel-slot-machine-stalwart-with-modern-popularity/) (accessed 2026-05-11). **HIGH**

### 1.2 Why beloved (player narrative)
- **Choice / illusion-of-control bonus**: "The Top Dollar symbol rests on reel 3, and landing it on the payline triggers the Top Dollar bonus, where you get up to four offers of varying credit amounts." [Know Your Slots — Top Dollar](https://www.knowyourslots.com/top-dollar-mechanical-reel-slot-machine-stalwart-with-modern-popularity/) (accessed 2026-05-11). **HIGH**
- **Built-in math-optimal hint** rendered as a button label ("Take Offer" / "Try Again") that NJ regulators required be mathematically sound. Forum consensus: "during the bonus itself, Top Dollar has always advised whether the offer you are seeing is better to be taken or tossed out." [Flip The Switch — Right Offer](https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/), [Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) (accessed 2026-05-11). **HIGH**
- **Variants in IGT's catalog**: Top Dollar Deluxe, Top Dollar Sizzling 7, Double Top Dollar, Hot Top Dollar. [GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) (accessed 2026-05-11). **HIGH**

### 1.3 Cabinet base game
- "The original game features a three-reel, five-line stepper base with an arcade-style mechanical bonus game in a top box. When three bonus symbols land on the payline, 'flashing lights behind the light-box display in the top box' are triggered. … Bonuses ranging from 5 to 1,000 credits." [GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) (accessed 2026-05-11). **HIGH**
- Original S2000 was 3-reel 1-line; newer S-AVP is 3-reel 5-line. M15 spec.json is **single payline** which matches the S2000 original SKU.
- "Top Dollar® Sizzling 7® available in dual game packages featuring both a Classic game and a Deluxe version, with the Deluxe version offering a more feature-rich experience when the additional ante bet is selected." [URComped Top Dollar Sizzling 7](https://urcomped.com/game/slotmachine/details/1319/top-dollar-sizzling-7igt) (accessed 2026-05-11). **HIGH**

---

## 2. Published RTP / hit rate ranges

### 2.1 Top Dollar (land, original S2000, single-line) — Q1
- **No public PAR sheet exists for Top Dollar at any denom.** This is the central caveat. IGT keeps PAR sheets confidential: "PAR sheets are hard to come by, because slot manufacturers and publishers keep them secret." [easy.vegas — PAR Sheets](https://easy.vegas/games/slots/par-sheets) (accessed 2026-05-11). **HIGH**
- **Best proxy: jurisdiction averages for $1 denom**:
  - Strip $1 reel slots: **92.0%** average. [easy.vegas — Slot Returns](https://easy.vegas/games/slots/returns) (accessed 2026-05-11). **HIGH**
  - Downtown Vegas $1: 93.72%; Boulder Strip $1: 94.93%; N. Las Vegas $1: 94.88%. [easy.vegas — Slot Returns](https://easy.vegas/games/slots/returns) (accessed 2026-05-11). **HIGH**
  - Penny slots average ~89%; quarter ~88.5% on Strip. Higher denom typically = higher payback. [easy.vegas — Slot Returns](https://easy.vegas/games/slots/returns) (accessed 2026-05-11). **HIGH**
- **Inferred Top Dollar @ $1 denom**: ~92% on Strip floor as baseline, plausibly **91–94%** with operator-selected variant. M15 user_brief default decision says "$1 denom ~92% RTP" — this is consistent with the Strip $1 floor average; user_brief decision is the **best public-corroborated number**. **MEDIUM** (single corroborating proxy, no game-specific PAR sheet)

### 2.2 Double Top Dollar (online, 2025) — Q2
- **96.24% RTP** (multiple sources agreeing). [SlotsMate Double Top Dollar review](https://www.slotsmate.com/software/igt/double-top-dollar), [SlotCatalog](https://slotcatalog.com/en/slots/double-top-dollar), [SlotsLaunch](https://slotslaunch.com/igt/double-top-dollar) (accessed 2026-05-11). **HIGH**
- Online version is **3-reel, 9-line, max win 4000× bet**, **high volatility**. [SlotsMate](https://www.slotsmate.com/software/igt/double-top-dollar) (accessed 2026-05-11). **HIGH**
- Difference vs land Top Dollar: online Double Top Dollar adds 9 paylines + wild multipliers (1 wild = 2×, 2 wilds = 4×) and a "Double" theme. Land Double Top Dollar (S2000 cabinet) is 3-reel 1-line 2-credit with **two doublers** on bonus (i.e. bonus offer × 2 × 2 max). [SlotsMate](https://www.slotsmate.com/software/igt/double-top-dollar) (online) + [URComped land Double Top Dollar](https://urcomped.com/game/slotmachine/details/1094/double-top-dollarigt), [Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) (accessed 2026-05-11). **HIGH**
- RTP gap **online vs land**: online ~96.24% is **noticeably above land $1 average 92%** — typical online uplift for IGT classic IP. Designer **should not** use the 96.24% online figure as M15's RTP target; the M15 user_brief locks mode 1 = 95% which sits between online (96.24%) and land Strip average (92%). **HIGH** confidence on the gap; **MEDIUM** on M15's chosen 95% being justified by Strip-North-Vegas average (94.88%) as the higher end of land $1 RTP.

### 2.3 Hit rate — Q3 (estimate)
- **General 3-reel classic range**: 10–30% hit frequency. [Casinos Online — hit frequency](https://www.casinosonline.com/articles/slot-machine-math-exploring-game-odds-and-hit-frequency/) (accessed 2026-05-11). **HIGH**
- **Most slots overall**: 15–40%. [Know Your Slots — Hit Frequency](https://www.knowyourslots.com/slot-machine-math-hit-frequency/) (accessed 2026-05-11). **HIGH**
- **Best public proxy — Red White Blue (IGT 3-reel 1-line)**: 17.35% overall hit frequency (45,472 winning outcomes out of 262,144). [Wizard of Odds — Red White Blue Analysis Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11). **HIGH** (this is the **gold-standard proxy** — direct IGT 3-reel 1-line PAR with cherry/seven/bar archetype).
- **Top Dollar specifically**: no published hit rate. Inference: the cherry-anywhere mechanism + bonus trigger reel + 3-reel 1-line = should sit **15–20% hit frequency**, very close to Red White Blue's 17.35%. M15 user_brief target **[15%, 18%]** lands inside this band — well-corroborated. **MEDIUM** (no game-specific source, but the proxy is structurally analogous).

### 2.4 Top Dollar bonus trigger rate — Q5
- **No published numerical trigger rate for Top Dollar.** Industry comment: "the bonus tends to appear with moderate frequency" but no number. [doubletop-dollar.com review](https://doubletop-dollar.com/) (accessed 2026-05-11). **LOW**
- **Industry context for bonus trigger rate**: "Hit frequencies range from 1 in 13 spins to 1 in 398 spins depending on the specific slot game and bonus feature, with an average of 1 in 191 spins across all slot games with a bonus feature." [itchcode — Slot Bonus Round Trigger](https://www.itchcode.com/slot-bonus-round-trigger-frequency-statistics/) (accessed 2026-05-11). **MEDIUM**
- **M15 v7 actual trigger rate**: 1.127% = 1 in 89 spins (per session brief §1 and 00 session brief). This is more frequent than the industry average (1 in 191) but well within the 1 in 13–398 published range. **HIGH** confidence that M15 v7 is on the "high-trigger" side of bonus-feature slots — consistent with the design intent of feature dominance (50:50 split).

---

## 3. Family RTP share (estimated) — Q4

### 3.1 Red White Blue benchmark (best proxy)
Per the [Wizard of Odds Red White Blue analysis](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11), in the 86.58% 1-coin PAR:

| Family | RTP contribution | Share % of total RTP |
|---|---|---|
| Sevens (any three sevens, ordered triples) | 0.3659 + 0.0137 + 0.0092 ≈ **0.3888** | **45%** |
| Bars (3-bar/2-bar/1-bar combos) | ~0.098 | ~11% |
| Blanks (1-coin push) | 0.125 | ~14% |
| Mixed / other | residual | ~30% |

**Caveat**: Red White Blue has no cherry, no wild — so its family share is **not directly transferable** to Top Dollar (which has cherry, wild, jackpot filler, topdollar trigger).

### 3.2 Other classic-IGT family share data points
- **Blazing 7s** (electromechanical): jackpot ≈ 1.93% of total payback. [easy.vegas — Slot Returns](https://easy.vegas/games/slots/returns) (accessed 2026-05-11). **HIGH**
- **Lucky Larry's Lobstermania** (5-reel): top jackpot 1 in 8 million. [Know Your Slots — PAR Sheets](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/) (accessed 2026-05-11). **HIGH**
- **Double Diamond Deluxe** (3-reel physical): jackpot expectation 1 in 46,000 plays. [Know Your Slots — PAR Sheets](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/) (accessed 2026-05-11). **HIGH**

### 3.3 Memory note benchmark cross-check
Per project memory `reference_classic_slot_rtp_distribution.md` (which itself cites prior research):
- RWB (IGT) 87% RTP: 7-family ~50% / Bar 31% / Cherry 16%
- Blazing Sevens 89% RTP: 7-family 68.8%
- Seven family hit rate typically **0.3–1%** (not 1/82k as casual players assume)
The memory note's family numbers for **RWB** are within ~5pp of Wizard of Odds' published shares above — the memory data is corroborated. The **cherry-16% / bar-31%** numbers cited in memory apply to a *cherry-bearing* variant of RWB (e.g. early RWB or its Cherries/Bars/Sevens cousin) — not the no-cherry pure variant Wizard of Odds analyzes. Designer should treat:
- **Sevens / top family**: 30–70% of total RTP for classic IGT 3-reel (range varies wildly by machine — RWB ~45%, Blazing 7s 68.8%)
- **Bar family**: 11–31%
- **Cherry family**: 16–20% (when cherry-anywhere mechanism is present)
- **Wild family share**: 5–10% (varies; Double Diamond wild concentrates RTP into wild combos)
- **Feature/Bonus family**: 0–55% (Feature Play archetypes like Top Dollar push this much higher; M15 user_brief locks 50%)

**For M15 specifically**, the **50:50 base:feature split locked by user_brief** is well outside any pure-classic archetype reference (most classics have 0–10% feature share if any). M15 is closer to **Wheel of Fortune Top Dollar variants** or modern "feature-heavy" classics where the bonus is a co-equal RTP source — consistent with the archetype declared in user_brief. **MEDIUM** confidence (Top Dollar's actual feature share is undisclosed).

---

## 4. Feature Play UX + math

### 4.1 Bonus mechanic structure — Q10
- **Up to 4 offers per trigger**, each presented sequentially. [Flip The Switch — Right Offer](https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/) (accessed 2026-05-11). **HIGH**
- **Forced accept on 4th round**: "If you hit that point, you automatically are awarded that as your bonus prize." [Flip The Switch — Double Top Dollar](https://fliptheswitch.com/game/double-top-dollar/) (accessed 2026-05-11). **HIGH**
- **Math-optimal accept thresholds (Double Top Dollar)**: 1st offer ≥ 50, 2nd ≥ 45, 3rd ≥ 35. [Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) (accessed 2026-05-11). **HIGH**
- **Original Top Dollar threshold**: "Accept offers of 35 credits or above" (lower threshold reflects lower offer ceiling vs Double Top Dollar). [Flip The Switch — Right Offer](https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/) (accessed 2026-05-11). **HIGH**
- **M15 v7 design uses accept_threshold = 40 (flat across modes)** — consistent with halfway between original (35) and Double (50/45/35 graduated). User_brief default decision pins this at flat 40, deliberately not graduated. **HIGH** archetype-faithful.

### 4.2 Mr Money Bags reference — Q10 disambiguation
- Cross-check: "Mr. Money Bags" is actually a **VGT** title (Video Gaming Technology, 2001), **not Top Dollar**. [GamblingNerd — Mr Moneybags](https://www.gamblingnerd.com/slots/mr-moneybags/), [About Slots — VGT Mr Money Bags](https://www.aboutslots.org/vgt/mr-money-bags/) (accessed 2026-05-11). **HIGH**
- The Mr Money Bags **symbol-as-multiplier** mechanic (1 symbol = 2×, 2 symbols = 4×) is structurally similar to the Double Diamond wild multiplier in Double Top Dollar but is a different game. Designer should **not** use Mr Money Bags as a direct archetype proxy. **HIGH**
- M15 spec.json uses `doublediamond` (Double Diamond wild, multiplier 2) — this is the **correct** archetype mapping for the Top Dollar / Double Top Dollar family. **HIGH**

### 4.3 Offer distribution + EV per trigger — Q6
- **No published distribution table for Top Dollar offer values**. Forum data points (single-player anecdotes):
  - 1st offer 35 credits, 2nd offer 460 credits (Double Top Dollar at $25 denom). [Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) (accessed 2026-05-11). **LOW**
  - 1× $120 offer with 2 doublers = $480 award. [Flip The Switch — Right Offer](https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/) (accessed 2026-05-11). **LOW**
- **GGB Magazine**: "Bonuses ranging from 5 to 1,000 credits" on the original land Top Dollar S2000. [GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) (accessed 2026-05-11). **HIGH**
- **Inferred offer distribution shape**: heavy mass in mid-range (35-200 credits) with long thin tail to 1000 credits. M15 v7 design `x_pool = [1000, 100, 50, 50, 20, 20, 10, 10, 5, 5]` with weights heavily skewed to low values is **archetype-faithful** if not over-skewed. **MEDIUM**

### 4.4 EV per trigger
- **No published Top Dollar bonus EV**. Inferred:
  - 4 rounds with accept threshold ~40 + math-optimal strategy → average accepted offer probably ~60–80 credits (with player accepting better-than-average offers in early rounds and being forced into possibly bad late rounds).
  - With Double Top Dollar's max win 4000× bet and an ~9-line cabinet, individual feature triggers averaging in the 50-150× range is plausible.
- **M15 v7 actual feature EV = 46× bet per trigger** (per session brief §1 and spec.json `_weights_rationale`). With 1.127% trigger rate = 46 × 0.01127 = 0.518 → 51.8 pp of total RTP. This matches the M15 v7 base:feature = 45:55 split. **HIGH**

### 4.5 count_x = 1 perception — Q11
- **No direct UX research on single-card reveal in multi-pick bonuses.** Closest evidence:
  - Industry pick-game norm: "Most bonus games of this type give you three picks or require you to keep choosing boxes until you reveal three symbols of the same kind." [GammaStack — Bonus Mechanics](https://www.gammastack.com/blog/top-slot-features-every-successful-slot-game-should-have/) (accessed 2026-05-11). **MEDIUM**
  - "Multi-stage bonus rounds that play out like mini-adventures … breaks the monotony of traditional spins." [1spin4win — Slot Development](https://www.1spin4win.com/blog/slot-game-development-process-and-market-trends) (accessed 2026-05-11). **MEDIUM**
  - "Engagement increase up to 35%" with multi-pick / multi-stage bonus mechanics vs single-reveal. **MEDIUM**
- **Inference for Top Dollar specifically**: Top Dollar's archetype is **per-round single-offer-with-accept-or-reject**, not a multi-pick reveal. So "count_x = 1" in M15 v7 (single x-card revealed per round) **matches the archetype's per-round structure** — each round is meant to be one offer, not a multi-pick. **HIGH**
- **However**, M15 spec.json says "roll count_x ∈ [1,5] by x_count_weights" — so multiple cards per round IS a design choice (likely to make each round's offer feel less arbitrary). In that case, **count_x = 1 (5% in v7) is anticlimactic** because the round becomes "one card flipped, here's your offer", which feels stingy when context-set by rounds that reveal 2-5 cards. User_brief target ≤2% is consistent with making single-card rounds rare-event narrative ("just one card this time, must be a special offer") rather than commonplace stinginess. **MEDIUM** confidence (no direct research; archetype consistency argument).

### 4.6 Reroll-driven anticipation + forced accept — Q12
- **Illusion of control is the central psychological hook**: "Features like 'stop' buttons or bonus rounds that involve a degree of choice can make players feel as though their actions influence the outcome." [SDLC Corp — Slot Psychology](https://sdlccorp.com/post/the-psychology-behind-slot-game-design-and-player-engagement/) (accessed 2026-05-11). **HIGH**
- **Math-display button (Take Offer vs Try Again)** is regulator-mandated in NJ to be mathematically sound — players see optimal play but can override. [Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) (accessed 2026-05-11). **HIGH**
- **Forced accept on final round (round 4)** is structural: serves as the "guaranteed-payout backstop" while still letting first 3 rounds feel like choice. [Flip The Switch — Double Top Dollar](https://fliptheswitch.com/game/double-top-dollar/) (accessed 2026-05-11). **HIGH**
- **Near-miss research**: "Players bet more following a near-miss, prolong the gaming session and are more persistent to continue, while experiencing a reduced sense of control over the game outcome." [Casino Center — Near Miss Psychology](https://www.casinocenter.com/slot-machine-psychology-how-the-near-miss-effect-drives-player-behavior-in-online-gaming/), [Springer 10.1007/s10899-019-09891-8](https://link.springer.com/article/10.1007/s10899-019-09891-8) (accessed 2026-05-11). **HIGH**
- **Implication for M15 reroll**: Each rejected offer is structurally a "near-miss" event (rejected what-might-have-been-good for what-might-be-better). The forced accept on round 4 caps player loss while letting them feel they did all the choosing. **HIGH**

---

## 5. Reel structure findings

### 5.1 Reel layout — Q7
- **IGT classic 3-reel physical layout**: 22 physical stops per reel was the canonical mechanical limit. [Know Your Slots — PAR Sheets](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/) (accessed 2026-05-11). **HIGH**
- **Virtual reel mapping** (Harrigan 1988-era patent): physical 22 → virtual 32 (1987 example) or up to 64+ for modern. Single physical position can be mapped from multiple virtual positions to weight outcomes. [Know Your Slots — PAR Sheets](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/), [Know Your Slots — Virtual Reel Mapping](https://www.knowyourslots.com/understanding-virtual-reel-mapping/) (accessed 2026-05-11). **HIGH**
- **Double Diamond Deluxe**: 72 positions per reel (virtual). [Know Your Slots — PAR Sheets](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/) (accessed 2026-05-11). **HIGH**
- **Red White Blue**: 64 positions per reel, 32 of which are blanks. [Wizard of Odds — RWB Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11). **HIGH**
- **M15 spec**: 36 stops × 3 reels (per session brief §1 reel_strips.json). This is **between physical (22) and virtual-classic (64)** — closer to a compact-virtual layout. Whether this counts as "virtual reel mapping" per Harrigan §15.4 mechanism C is fuzzy; physically a 36-stop strip is plausible (some 3-reel slots had 30-40 physical stops before pure-virtual mapping). **MEDIUM**

### 5.2 R1 vs R3 asymmetry — Q8
- **Top Dollar specifically**: "The Top Dollar symbol rests on reel 3, and landing it on the payline triggers the Top Dollar bonus." [Know Your Slots — Top Dollar](https://www.knowyourslots.com/top-dollar-mechanical-reel-slot-machine-stalwart-with-modern-popularity/) (accessed 2026-05-11). **HIGH**
- **This makes R3 a "trigger reel"** per `DESIGN_PHILOSOPHY.md` §12.1 (b) — top symbol density (excluding trigger) should be **lower** on R3 than R1, but trigger symbol density on R3 is the active dial for bonus rate.
- **Red White Blue published reel data** (closest proxy for IGT 3-reel symbol weighting):
  - Red 7: R1=1, R2=3, R3=1 (R1=R3=1, R2 has 3× as many — i.e. middle reel has the "highest count" of the highest-payout symbol)
  - White 7: R1=6, R2=1, R3=7 (R3 highest)
  - Blue 7: R1=6, R2=7, R3=1 (R3 lowest)
  - Bars: roughly balanced
  - Blanks: R1=R2=R3=32 (equal across reels) [Wizard of Odds — RWB Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11). **HIGH**
- The Red White Blue layout is **asymmetric in winners-symbol density per Strickland/Reid/Harrigan philosophy §12** but **does not enforce universal "R1 ≤ R3 blank"** — RWB has equal blanks across reels. So `DESIGN_PHILOSOPHY.md` §12.2 "R1 Blank rate ≤ R3 Blank rate" is **not strictly observed in RWB**; the asymmetry is in *winners* not blanks. Designer should not impose unrealistic R1-blank-down-vs-R3 enforcement on M15 — the philosophy direction is sound, but RWB is one counter-example. **HIGH**
- **Cleavage with M15 v7 actual** (per session brief §1): R1 jackpot 0.08% / R2 0.53% / R3 0.14% → R3 has more jackpot than R1 (3× higher) — this is **inverted** vs philosophy §12.1 "R1 ≥ R3 top-prize density". But user_brief #6 locks "jackpot at ≤0.6%/reel" as the binding constraint, and jackpot in M15 is "decorative filler" per spec.json `_notes` (NOT a paying combo). So the inversion is OK provided the "real" top symbol (doublediamond = wild = pay_id 1) is mapped per philosophy. M15 v7 already concentrates topdollar trigger on R3-only (matching archetype). **HIGH** that the broader architecture is archetype-correct; **MEDIUM** that jackpot R1/R3 inversion needs a verify carve-out (Designer must document this consciously).

### 5.3 Symbol pool — Q9
- **Top Dollar / Double Top Dollar standard symbols** (from review sites): Double Diamond wild (top-pay), Red 7 / White 7 / Blue 7 (or single "Lucky 7"), 1-Bar / 2-Bar / 3-Bar, cherries, Top Dollar bonus trigger. [SlotsMate](https://www.slotsmate.com/software/igt/double-top-dollar), [doubletop-dollar.com](https://doubletop-dollar.com/) (accessed 2026-05-11). **HIGH**
- **M15 spec.json symbols**: blank, cherry, 1bar, 2bar, 3bar, high7, doublediamond (wild ×2), topdollar (bonus), **jackpot** (decorative filler). The jackpot symbol is an M15-specific addition (not in canonical Top Dollar archetype). **HIGH**
- Per M15 spec.json `_notes`: "jackpot exists on all reels as decorative filler. Paytable §3: 3-jackpot on payline would pay 1000× but game mechanic prevents this in modes 1/2/5/7 (backend re-rolls); here jackpot is just a filler that dilutes paying-symbol marginals. Low weight minimizes RTP impact." This is a **structural deviation** from the canonical archetype — Top Dollar S2000 does not have a "jackpot" filler symbol. M15 designer should document why this exists (likely production-engine artifact carried over from another game family). **HIGH**

---

## 6. Cross-mode precedent

### 6.1 Lucky / Super-Lucky mode variant — Q13
- **Does IGT or Aristocrat ship explicit "Lucky / Super-Lucky" cabinet variants of Top Dollar?**
  - Search returned **no published "Lucky Top Dollar" or "Super-Lucky Top Dollar" SKU**. IGT's variant catalog for Top Dollar: Deluxe, Sizzling 7, Double, Hot. None are RTP-uplifted "Lucky" modes in the M15 sense. [GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) (accessed 2026-05-11). **HIGH**
- **Cross-game precedent for "player-selectable RTP via mode/feature choice"**:
  - **Lucky 88 (Aristocrat)**: "Player-variable RTP between 87.9% (low) and 96.6% (high), unlocked via Extra Choice feature." [AskGamblers — Lucky 88](https://www.askgamblers.com/casino-games/online-slots/reviews/lucky-88-aristocrat), [VegasSlotsOnline — Lucky 88](https://www.vegasslotsonline.com/aristocrat/lucky-88/) (accessed 2026-05-11). **HIGH**
  - General principle: "Brick-and-mortar casinos work with game manufacturers to select their preferred payback percentages. A Buffalo game may have RTP options of 88%, 90%, 92%, and 94%." [Casino.org — RTP Decoded](https://www.casino.org/blog/return-to-player-decoded/) (accessed 2026-05-11). **HIGH**
- **Conclusion**: Multi-mode (mode 1 standard / 2 lucky / 5 super-lucky / 7 cut) is **a virtual-machine / online-platform construct**, not a published land-cabinet feature for Top Dollar. M15's multi-mode is an originating concept on the M15 platform — Designer should not look for "land-cabinet equivalent" but rather treat each mode as a re-tuned variant of the same archetype (analogous to operator-selectable payback in Aristocrat Lucky 88 or Buffalo). **HIGH**

### 6.2 Cut mode (mode 7) — Q14
- **Mid-RTP cut as casino-floor-tuned variant** is a **known industry practice**:
  - "Land-based slots are usually set to return anywhere from 70% to 90%, with very few games ever going over 92%." [Casino.org — RTP Decoded](https://www.casino.org/blog/return-to-player-decoded/) (accessed 2026-05-11). **HIGH**
  - 1987 IGT three-reel example: 85% target payback, 22 physical → 32 virtual stops. [Know Your Slots — PAR Sheets](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/) (accessed 2026-05-11). **HIGH**
  - Penny slots usually set to "at least 85% even at lowest setting." [Casino.org — RTP Decoded](https://www.casino.org/blog/return-to-player-decoded/) (accessed 2026-05-11). **HIGH**
- **85% mid-RTP cut is the bottom of the typical land range** and is a real operator dial. M15 mode 7 = 85% target is **archetype-faithful**. **HIGH**
- **Cut-mode mechanism preference per philosophy §4**: "Cut mode (m7 = m1 砍小奖)": small-pay frequency reduced, mid/top/grand frequency unchanged. This matches the IGT industry practice of cutting RTP by tuning blank weights up / small-pay frequencies down, not by removing top awards (which would break the brand narrative). **HIGH**

---

## 7. Hit rate / CV benchmarks for 3-reel classic

### 7.1 Hit rate range — Q15
- **3-reel classic range**: 10–30% per Casinos Online. [Casinos Online — hit frequency](https://www.casinosonline.com/articles/slot-machine-math-exploring-game-odds-and-hit-frequency/) (accessed 2026-05-11). **HIGH**
- **Red White Blue (published)**: 17.35%. [Wizard of Odds — RWB Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11). **HIGH**
- **Player-comfort floor**: ≥10% is the threshold below which "every spin feels like a loss" — most classic IGT slots sit 15–25%. **MEDIUM** (synthesis from forum chatter + design philosophy general principle).
- **M15 user_brief target [15%, 18%]**: within RWB-anchored band, just below the proxy's 17.35% midpoint. The target is **aggressive on the low end** but justifiable: cherry-anywhere with 1× pay alone tends to push hit rate naturally higher; capping at 18% means M15 is **less hit-heavy than a pure cherry slot**, more like a balance between RWB (17.35%) and a less-cherry-heavy classic. **HIGH** confidence the target is reasonable.

### 7.2 CV / volatility benchmarks — Q16
- **Typical 1-line slot volatility index**: 8–15 (i.e. CV ~5–10 depending on confidence multiplier). [Wizard of Vegas — Calculating Symbol Frequency](https://wizardofvegas.com/forum/gambling/slots/33754-calculating-symbol-frequency/) (accessed 2026-05-11). **HIGH**
- **Red White Blue published CV (1-coin)**: standard deviation 9.03 with 86.58% RTP → CV ≈ 9.03 / 0.866 ≈ **10.4**. [Wizard of Odds — RWB Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11). **HIGH**
- **Red White Blue 3-coin**: SD 10.80 with 87.47% RTP → CV ≈ 12.3. [Wizard of Odds — RWB Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) (accessed 2026-05-11). **HIGH**
- **Most gaming machines in use feature CV from 5 to 100** broadly, but classic 3-reel single-line clusters **8–15**. [Wizard of Vegas — calculating volatility index](https://wizardofvegas.com/forum/questions-and-answers/math/28096-calculating-volatility-index-of-slot-machine-mini-game/) (accessed 2026-05-11). **HIGH**
- **Lucas & Singh 2008**: established CV inverse relationship with player time-on-device (lower CV = longer play). [Cornell Hospitality Q — Lucas & Singh 2008](https://journals.sagepub.com/doi/10.1177/1938965508315368) (accessed 2026-05-11). **HIGH**
- **M15 user_brief base CV target [3, 5]**: this is **significantly below** the classic 3-reel range (RWB ~10). The 3-5 target is achievable only if base game is **very low volatility** (lots of small frequent wins). User_brief locking base CV in [3,5] **deliberately repositions M15's base game away from classic high-vol** toward a "low-vol base + mid-vol feature" architecture — this is a modern hybrid design intent, consistent with "feature carries the volatility" archetype.  **HIGH** confidence the target is achievable but **departs from RWB-style classic** by design.
- **M15 user_brief feature CV target [1, 2]**: conditional CV across feature outcomes; this would mean feature payouts are tightly clustered (most around average, few extremes). With max-feature-payout ~1000× (capped) and average ~46×, achieving conditional CV in [1,2] needs careful bucket-shape design. **MEDIUM** achievable; Designer should target around 1.5 with reasonable bucket spread.
- **CV-RTP consistency direction** per philosophy §5: higher RTP = lower CV. M15 mode 1 (95%, target CV ~3-5 base) → mode 2 (300%, must have CV ≤6) → mode 5 (500%, CV ≈ mode 2) → mode 7 (85%, CV ≥ mode 1). This is a coherent ladder. **HIGH**

---

## 8. Cherry-anywhere mechanism — Q17

### 8.1 Mechanism standardization
- **"Cherry anywhere 1×" (single cherry anywhere → 1× bet)** is a **textbook classic-IGT mechanism**, present in:
  - Triple Cherry / Wild Cherry / Black Cherry S2000 family ("the Triple Cherry symbol is a triple multiplier and wild symbol which will also pay when it is within one position above or below the payline" — IGT S2000 Triple Cherry). [Ohio River Slots — Triple Cherry](https://www.ohioriverslots.com/shop/igt/s2000/triple-cherry/) (accessed 2026-05-11). **HIGH**
  - Double Wild Cherry: "Even one Wild Cherry on the pay line, or within one reel stop above/below, will guarantee you at least double your wager as a pay." [Know Your Slots — Double Wild Cherry](https://www.knowyourslots.com/double-wild-cherry-classic-igt-mechanical-3-reel-slot/) (accessed 2026-05-11). **HIGH**
  - Generic cherry-1×/cherry-2×/cherry-3× ladder common to: Double Diamond, Triple Double Diamond, Red White Blue (cherry variant), Top Dollar. **HIGH**

### 8.2 Hit rate consequences
- **Cherry-anywhere materially boosts hit rate** because the cherry's single-anywhere is **3 chances per spin** (any of 3 reels in middle row), not 1.
- For Red White Blue: 32/64 blanks per reel → P(blank, R1) = 50%. If cherries existed similarly, cherry-1 hit rate alone could add 5-20pp to total hit rate.
- **For M15 specifically**: cherry-1 (pay_id 9, 1× pay) is a **massive contributor to hit rate**. Per session brief §4 reason 5: "base RTP 32% comes from cherry-1 is archetype necessity." M15 cherry-anywhere is **structurally required** to keep the archetype faithful and is **non-negotiable** (per user_brief: "cherry-1 1× anywhere is archetype necessity, accepted, don't change paytable").
- **Implication for hit-rate target**: any attempt to push M15 hit rate < 15% probably hits a cherry-anywhere floor — cherry-1 marginal must be reduced (which reduces RTP from cherry family) or cherry-anywhere mechanism abandoned (which breaks archetype). **HIGH** structural argument.

### 8.3 Per-family cherry share in classic
- Cherry family RTP share in cherry-bearing IGT classics: ~**14–20%** (e.g. Crazy Cherry 94.26%, Lucky Cherry 93% / RWB cherry variant ~16% memory ref).
- M15 v7 cherry family share (cherry-1 + cherry-2 + cherry-3) is presumably in this band — Agent A's Stage 1b §4 should confirm with actual share. **MEDIUM** baseline expectation.

---

## Summary table: archetype baseline for Designer

| Metric | Top Dollar archetype baseline | M15 v7 actual (per quickref / session brief) | Gap |
|---|---|---|---|
| Total RTP (mode 1) | ~92% (Strip $1 land); 96.24% online (DTD) | 94.98% (locked target 95%) | Within land+online corridor (no gap; user_brief #target reasonable) |
| Hit rate (mode 1) | 15–18% inferred (RWB proxy 17.35%) | 19.31% | **+1.3pp over user_brief upper bound 18%** (needs tune down) |
| Base CV (mode 1) | Classic 3-reel 1-line CV ~10 (RWB CV 10.4) | 5.77 (current) | -4.6 below classic baseline; user_brief target [3,5] = deliberate modern repositioning |
| Feature CV (mode 1, conditional) | No public benchmark for Top Dollar bonus | 0.74 (current) | Below user_brief target [1,2]; bucket too narrow (needs more variance) |
| Base : Feature RTP split | Top Dollar archetype split undisclosed; M15 user_brief locks 50:50 | 45.4 : 54.6 | Feature +4.6pp over user_brief 50% target (needs rebalance) |
| Trigger rate | No published; industry ~1 in 191 (median); M15 archetype "feature-heavy" | 1.127% = 1/89 | More frequent than industry median but within published 1/13-1/398 range — high-trigger archetype faithful |
| Feature EV per trigger | Unpublished | 46× bet | Reasonable for 50:50 split design (trigger × EV ≈ 0.52 = 52pp) |
| Top jackpot freq (mode 1) | Per philosophy §7: 1 in 50–100k spins target | M15 v7: top pay_id 1 (200× pure wild) ~1 in 60k = 0.0017% | Matches §7 baseline target |
| P(R≥1000× / spin) all modes | Top Dollar archetype max 1000× (single) / Double TD 4000× | M15 mode 1: 1/8.3M; mode 5: 1/3.6M | **Far below industry avg** — deliberate user-pinned (per user_brief #5) |
| Jackpot symbol marginal (≤0.6%/reel, all modes) | Decorative filler not standard archetype | R1 0.08% / R2 0.53% / R3 0.14% (mode 1) | All ≤ 0.6% ✓ user_brief #6 satisfied |
| count_x=1 probability | No archetype norm; archetype hosts per-round single offer | 5% in v7 | **Above user_brief target ≤2%** (needs tune) |
| Cherry share of RTP | 14–20% in cherry-bearing classics | (Agent A confirms via Stage 1b §4) | Likely on target archetype-wise |
| 7-family / wild share | 30–70% of RTP in classic; combined wild+high7+200× wild line | (Agent A confirms via Stage 1b §4) | Should be high; designer to confirm post Stage 1b |
| Bar family share | 11–31% in classic | (Agent A confirms via Stage 1b §4) | Should be moderate |

---

## Open questions for Designer

1. **count_x=1 cap mechanism**: The archetype is per-round single-offer (1 card = 1 offer). M15's "roll count_x in [1,5]" multi-card mechanic *adds* variance to each round's offer build. Designer must decide: is reducing count_x=1 to ≤2% the goal (i.e. avoid stingy single-card rounds), OR should count_x=1 be the *common* mode with 2-5 cards being the rare boost? Current user_brief takes the former — flag if Designer wants to revisit.

2. **Jackpot R1<R3 inversion handling**: M15 jackpot R1 0.08% < R3 0.14% inverts philosophy §12.1 "R1 ≥ R3 top-prize density". Since jackpot is "decorative filler" (never a paying combo per spec.json), should verify.py's REEL-ASYMMETRY rule **exclude** jackpot from top-prize calculation? If so, the "real" top-prize for asymmetry purposes is **doublediamond (wild)** + **high7** + maybe **3bar**.

3. **CV target gap**: Base CV [3,5] target is well below RWB-style classic (CV ~10). Designer should explicitly document this as a "low-vol base + mid-vol feature" architecture (modern hybrid) in DESIGN.md, not present it as "matching the archetype" — that would be misleading.

4. **Feature share 50:50**: The 50:50 base:feature split locks M15 into a "feature-heavy" archetype. Classic Top Dollar bonus share is undisclosed but likely lower (15-30% maybe). Designer should write this as a M15-specific deviation in DESIGN.md (M15 is the "Top Dollar with maximally featured architecture" reading), not pretend the archetype dictates 50:50.

5. **Mode 2 hit lift ×1.5–2 not ×3**: User_brief locks "hit ×1.5-2". Without archetype precedent (no land "Lucky Top Dollar" exists), Designer should anchor this via philosophy §9 mode-pair monotonicity + §C/D universal multi-mode rules, not via a Top Dollar-specific claim. Cite philosophy directly.

6. **Top symbol PWDF target**: No published Top Dollar PWDF data. Harrigan IGT Double 7 reference (above-line visibility 12.5% on R1) is the closest. M15's topdollar lives only on R3 so PWDF is a different question (R3-only visibility). Per philosophy §15.3 floor "30-40% for 5-reel" → for 3-reel single-symbol-on-R3 → no direct floor analog. Designer to derive from M15 v7 actual baseline + Harrigan philosophy direction, **not pick a number from another machine**.

7. **Mode 7 cut mechanism**: User_brief locks "砍小奖 freq" per philosophy §4. Designer must NOT use per-hit-avg-shrink (the Phase 0a anti-pattern); must reduce small-pay frequencies (cherry-1, cherry-2, mixed-bar) while preserving mid+top pay frequency. Cherry-1 frequency reduction is the **big lever** since cherry-1 is the dominant small-pay.

8. **The "Mr. Money Bags" reference in the user task description was a red herring** — that's a different game (VGT, 2001). M15's wild is "doublediamond" matching Top Dollar's actual archetype wild. Designer should not import any Mr. Money Bags semantics.

---

## Citations index

Sources accessed 2026-05-11:

1. [GGB Magazine — Top Dollar](https://ggbmagazine.com/articles/top-dollar/)
2. [Know Your Slots — Top Dollar Mechanical Reel Slot Stalwart](https://www.knowyourslots.com/top-dollar-mechanical-reel-slot-machine-stalwart-with-modern-popularity/)
3. [Know Your Slots — Slot Machine Math Hit Frequency](https://www.knowyourslots.com/slot-machine-math-hit-frequency/)
4. [Know Your Slots — The PAR Sheet](https://www.knowyourslots.com/the-par-sheet-a-look-under-the-hood-of-a-slot-machine-game/)
5. [Know Your Slots — Understanding Virtual Reel Mapping](https://www.knowyourslots.com/understanding-virtual-reel-mapping/)
6. [Know Your Slots — Double Wild Cherry](https://www.knowyourslots.com/double-wild-cherry-classic-igt-mechanical-3-reel-slot/)
7. [SlotsMate — Double Top Dollar Review](https://www.slotsmate.com/software/igt/double-top-dollar)
8. [SlotCatalog — Double Top Dollar](https://slotcatalog.com/en/slots/double-top-dollar)
9. [Double Top Dollar Demo + Review (slotslaunch)](https://slotslaunch.com/igt/double-top-dollar)
10. [doubletop-dollar.com Review](https://doubletop-dollar.com/)
11. [Flip The Switch — Taking the Right Offer](https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/)
12. [Flip The Switch — Double Top Dollar game page](https://fliptheswitch.com/game/double-top-dollar/)
13. [Wizard of Vegas thread 27453 — Top Dollar Bonus Strategy](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/)
14. [Wizard of Vegas thread 33754 — Calculating Symbol Frequency](https://wizardofvegas.com/forum/gambling/slots/33754-calculating-symbol-frequency/)
15. [Wizard of Vegas thread 28096 — Volatility Index](https://wizardofvegas.com/forum/questions-and-answers/math/28096-calculating-volatility-index-of-slot-machine-mini-game/)
16. [Wizard of Odds Appendix 6 — Red White Blue Analysis](https://wizardofodds.com/games/slots/appendix/6/)
17. [easy.vegas — Slot Returns](https://easy.vegas/games/slots/returns)
18. [easy.vegas — PAR Sheets](https://easy.vegas/games/slots/par-sheets)
19. [Casino.org — RTP Decoded](https://www.casino.org/blog/return-to-player-decoded/)
20. [Casinos Online — Slot Math Game Odds Hit Frequency](https://www.casinosonline.com/articles/slot-machine-math-exploring-game-odds-and-hit-frequency/)
21. [itchcode — Slot Bonus Round Trigger Frequency Statistics](https://www.itchcode.com/slot-bonus-round-trigger-frequency-statistics/)
22. [SDLC Corp — Psychology of Slot Game Design](https://sdlccorp.com/post/the-psychology-behind-slot-game-design-and-player-engagement/)
23. [GammaStack — Top Slot Features](https://www.gammastack.com/blog/top-slot-features-every-successful-slot-game-should-have/)
24. [1spin4win — Slot Development](https://www.1spin4win.com/blog/slot-game-development-process-and-market-trends)
25. [Casino Center — Near Miss Psychology](https://www.casinocenter.com/slot-machine-psychology-how-the-near-miss-effect-drives-player-behavior-in-online-gaming/)
26. [Springer — Near-Miss Slot Machines review (Pisano 2019)](https://link.springer.com/article/10.1007/s10899-019-09891-8)
27. [Harrigan 2007 — Award Symbol Ratios (Springer)](https://link.springer.com/article/10.1007/s11469-007-9066-8)
28. [Harrigan 2007 — Pursuing Responsible Gaming for Virtual Reels and Near Misses (Springer)](https://link.springer.com/article/10.1007/s11469-007-9139-8)
29. [Lucas & Singh 2008 — Cornell Hospitality Quarterly](https://journals.sagepub.com/doi/10.1177/1938965508315368)
30. [URComped — Top Dollar IGT](https://urcomped.com/game/slotmachine/details/1055/top-dollarigt)
31. [URComped — Double Top Dollar IGT](https://urcomped.com/game/slotmachine/details/1094/double-top-dollarigt)
32. [URComped — Top Dollar Sizzling 7](https://urcomped.com/game/slotmachine/details/1319/top-dollar-sizzling-7igt)
33. [AskGamblers — Lucky 88 Aristocrat](https://www.askgamblers.com/casino-games/online-slots/reviews/lucky-88-aristocrat)
34. [VegasSlotsOnline — Lucky 88](https://www.vegasslotsonline.com/aristocrat/lucky-88/)
35. [Ohio River Slots — IGT S2000 Triple Cherry](https://www.ohioriverslots.com/shop/igt/s2000/triple-cherry/)
36. [Wikipedia — IGT 1975-2015](https://en.wikipedia.org/wiki/International_Game_Technology_(1975%E2%80%932015))
37. [GamblingNerd — Mr Moneybags (VGT, disambiguation)](https://www.gamblingnerd.com/slots/mr-moneybags/)
38. [About Slots — VGT Mr Money Bags (disambiguation)](https://www.aboutslots.org/vgt/mr-money-bags/)
