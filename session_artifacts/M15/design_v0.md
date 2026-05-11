# M15 Design — v0 narrative (Stage 4 working draft)

> **Agent**: Designer (D) per [`slot_designer/ONBOARDING_PROCESS.md`](../../slot_designer/ONBOARDING_PROCESS.md) §4 D row + §5 Stage 4.
>
> **Generated**: 2026-05-11.
>
> **Status**: Working draft. Will be promoted to canonical `machines/M15/DESIGN.md` + `MODE_DESIGN.md` only after Stage 4 review by Critic (X).
>
> **Inputs read (in truth-order)**:
> 1. R archetype `01d_research.md` (truth layer 1 — outside knowledge)
> 2. A baseline `01b_baseline_report.md` (truth layer 1 — inside data, v7 measured)
> 3. `slot_designer/DESIGN_PHILOSOPHY.md` §1-15 (truth layer 2)
> 4. `user_brief.md` (truth layer 3)
> 5. `process_improvements.md` (#2/#3/#5/#8 — contamination + signal flags)
> 6. `slot_designer/machines/M15/spec.json` (mechanism only — `_design`/`_notes`/`_weights_rationale` IGNORED per #2/#3)
> 7. `slot_designer/machines/M15/reel_strips.json` (36 stops × 3 reels)
> 8. `slot_designer/machines/M15/plugins/feature.py` (`FeatureSpec` parameter contract)
> 9. `slot_designer/core/tuner/target_profile.py` (target file schema; `extract_target` snapshot fields)
>
> **Not read** (contamination firewall per task brief): sister-machine targets, deleted DESIGN.md/MODE_DESIGN.md/NOTES.md, weights.json `_tuned_summary` / `feature_params._analytic`, spec.json `_design`/`_notes`/`_weights_rationale`, memory entries with M15 numbers.

---

## 1. Archetype reference (truth layer 1)

### 1.1 Lineage and SKU disambiguation

- **Top Dollar (IGT, S2000 cabinet, 3-reel × 1-payline)** is the primary archetype. Originally a Barcrest game; IGT acquired Barcrest 1998. Persistent casino-floor presence ([GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) — accessed 2026-05-11, HIGH).
- M15 spec.json is 3-reel × 1 payline ([`spec.json` grid.paylines`]) — matches the S2000 SKU, not the S-AVP 5-line variant.
- Cited variants in IGT catalog: Top Dollar Deluxe / Sizzling 7 / Double / Hot ([GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) — HIGH). **No "Lucky Top Dollar" or "Super-Lucky Top Dollar" SKU exists** — multi-mode is a M15-platform construct (see §4 / §6.1 of 01d_research).
- M15 wild is `doublediamond` (multiplier 2) — matches Top Dollar's "Double Diamond wild" archetype (`spec.json` symbols.doublediamond.multiplier`). The Mr. Money Bags reference in the original SESSION_BRIEF was a different game (VGT 2001) and should NOT be cited (01d_research §4.2; process_improvements #12).

### 1.2 Bonus mechanic structure (archetype-faithful)

- **Up to 4 offers per trigger, forced accept on round 4** ([Flip The Switch — Right Offer](https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/) — HIGH; [Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) — HIGH).
- **Math-optimal accept threshold for original Top Dollar**: ≥35 credits. Double Top Dollar graduated 50/45/35 by round ([Wizard of Vegas thread 27453](https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/) — HIGH).
- M15 v7 uses **accept_threshold = 40 flat** — between original (35) and Double (graduated 50/45/35). user_brief default decision pins this at flat 40 and explicitly **declines to restore graduated**.
- **Offer range archetype**: 5 to 1,000 credits ([GGB Magazine](https://ggbmagazine.com/articles/top-dollar/) — HIGH). M15's `x_pool = (1000, 100, 50, 50, 20, 20, 10, 10, 5, 5)` directly maps this.

### 1.3 RTP / hit-rate proxies

- **No published Top Dollar PAR sheet exists** at any denom ([easy.vegas — PAR Sheets](https://easy.vegas/games/slots/par-sheets) — HIGH). All archetype numbers below are proxy-derived.
- **Best public structural proxy: Red White Blue (IGT 3-reel × 1-line)** with full PAR ([Wizard of Odds — Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) — HIGH):
  - hit_rate = **17.35%** (45,472 / 262,144).
  - 1-coin RTP = 86.58%; std_return = 9.03 → **CV ≈ 10.4**.
- **Modern proxy: Double Top Dollar (IGT, online, 2025 release)** ([SlotsMate](https://www.slotsmate.com/software/igt/double-top-dollar) — HIGH; [SlotCatalog](https://slotcatalog.com/en/slots/double-top-dollar) — HIGH):
  - RTP = **96.24%**, "high volatility", max win 4000× bet.
- **Jurisdiction average for Strip $1 reel slots: 92.0%** ([easy.vegas — Slot Returns](https://easy.vegas/games/slots/returns) — HIGH). user_brief default "$1 denom ~92% RTP" cites this.
- **Bonus trigger industry range**: 1/13 to 1/398, median 1/191 ([itchcode](https://www.itchcode.com/slot-bonus-round-trigger-frequency-statistics/) — MEDIUM). M15 v7's 1/89 is well within range, on the higher-trigger side (consistent with 50:50 feature-heavy design).

### 1.4 Reel role per Top Dollar archetype

- **R3 is the trigger reel**: "The Top Dollar symbol rests on reel 3, and landing it on the payline triggers the Top Dollar bonus." ([Know Your Slots — Top Dollar](https://www.knowyourslots.com/top-dollar-mechanical-reel-slot-machine-stalwart-with-modern-popularity/) — HIGH). M15 `reel_strips.json` `_invariants` row 2 confirms: "topdollar ONLY on reel 3".
- **Per DESIGN_PHILOSOPHY §12.1 (b)**: M15's R3 takes the **(b) trigger reel role** — top-prize density (excl trigger) should be **lower** on R3 than R1; trigger symbol density on R3 is the active dial for bonus rate.
- **Red White Blue per-reel symbol weighting** (closest IGT 3-reel weighting datum, [Wizard of Odds — Appendix 6](https://wizardofodds.com/games/slots/appendix/6/) — HIGH):
  - Red 7: R1=1, R2=3, R3=1 (middle has highest count of top symbol)
  - White 7: R1=6, R2=1, R3=7 (R3 highest)
  - Blue 7: R1=6, R2=7, R3=1 (R3 lowest)
  - Blanks: equal across reels (R1=R2=R3=32)
  - **Note**: RWB does NOT enforce universal "R1 ≤ R3 blank". Asymmetry is in winners not blanks. M15 should not over-tighten R1<R3 blank — 01b §6 already shows m1 Δ(R3-R1) blank = +0.01pp (essentially equal), and modes 2/5/7 actually have R3 BLANK LESS than R1 (because R3 holds topdollar instances that displace blanks). Direction lock per philosophy §12.2 is OK to keep but tolerance must accommodate the "trigger displacement" structural fact.

---

## 2. Universal philosophy applied (truth layer 2)

Citation key: §N = `DESIGN_PHILOSOPHY.md` §N.

### 2.1 Per-family payout-frequency inverse pyramid (§1)

M15 v7 family RTP (01b §4, mode 1 base RTP = 43.15pp):
- cherry1 P=13.77% (1× pay) → cherry2 P=0.71% (5×) → cherry3 P=0.011% (15×): cherry pyramid ordered correctly, frequency ratios 19×, 65× across tiers.
- bar1 P=0.25% (5×) → bar2 P=0.58% (10×) → bar3 P=0.11% (20×): **mid-bar order violated** — bar2 has HIGHER frequency than bar1 despite higher payout. Already an archetype-driven artifact (M15 paytable §2-3: 1bar=5×, 2bar=10×, 3bar=20×; v7 weight allocation gives bar2 higher representation than bar1 for unknown historic reason). **Design target**: enforce bar1 P ≥ bar2 P ≥ bar3 P in v0 weights (cite §1 verbatim).
- bar_mixed P=3.86% (2×) is the mixed-bars 3-of-a-kind and lives outside per-bar hierarchy.
- high7_pure P=0.003% (30×) vs high7_wild P=0.014% (30×): same payout, different mechanism — wild substitution makes wild-included variant 4.6× more frequent, consistent with §1 (substituted-required combos are physically more reachable).

### 2.2 Brand symbol visibility (§2)

M15 brand symbols (cite `spec.json` symbols):
- `doublediamond` — wild + brand (Double Diamond family) — `kind="wild", multiplier=2`
- `topdollar` — feature trigger / brand — `kind="filler"`, R3 only
- `high7` — second-tier brand (Top Dollar / Sizzling 7 family)
- `jackpot` — decorative filler, **NOT a paying symbol** (`spec.json._notes` row 4: "jackpot... never awards 1000× prize on normal spins; backend re-rolls; decorative filler"). Excluded from brand visibility scope.

v7 baseline 01b §7 PWDF (mode 1 any-reel max p_window):
- doublediamond = 15.83% (R2), high7 = 17.15% (R2), topdollar = 13.24% (R3 only)
- PWDF ratio = p_window/p_mid ranges 4.29-7.14 for doublediamond, 3.42-7.14 for high7 — well above 1× baseline.
- These are physical-reel visibilities (no virtual mapping); per §15.3 floor 30-40% requires virtual mapping. M15 is physical (36 stops; per 01d §5.1 between physical 22 and virtual 64).

**Design**: Keep mode 1 any-reel window visibility for top-prize symbols ≥ v7 measured floor. **No machine-specific PWDF target in v0** — design focuses on numerical optimization, not visibility redesign. Cite §15.6: "physical reel: PWDF not in tune cost; post-tune RTP-neutral redistribution if needed". v0 deferred.

### 2.3 Blank weight cap headroom (§3)

v7 blank marginal: m1 R1 54.50% / R2 54.62% / R3 54.51% (01b §5). Strict B-N alternation per reel (`reel_strips.json` `_invariants` row 1: "Blank/non-blank strict alternation per reel"). Blanks are 18/36 per reel = 50% physical positions — weights drive the 54%+ marginal (non-blank positions partially diluted by jackpot filler). Headroom topic doesn't apply at strip level — blank weight is a function of `weights.json` totals per stop. **v0 design: keep ≥5 weight headroom per blank stop in optimization** (cite §3).

### 2.4 Per-tier hit preservation (§4)

Cut mode (mode 7 = mode 1 砍小奖):
- v7 m7 hit = 14.92% vs m1 19.31% — m7 lower hit ✓ (01b §1 / §11 `MODE7_LOCK_mode7_hit_lt_mode1`)
- Per-pay tier check (01b §3 m7 vs m1):
  - cherry1 (small): m7 P=10.996% vs m1 P=13.771% → **-2.78pp = small-pay cut ✓**
  - bar_mixed (small): m7 P=2.76% vs m1 P=3.86% → -1.10pp = small-pay cut ✓
  - bar2 (mid): m7 P=0.42% vs m1 P=0.58% → -0.16pp = mid-pay cut (should be smaller delta — per §4 "中/大/顶奖 hit 不动")
  - wild_pure (top): m7 P=0.00178% vs m1 P=0.00166% → +0.00012pp = **top unchanged ✓**
- **Design**: m7 must cut cherry1 / bar_mixed (small) deeper; keep bar2 / bar3 / high7 / wild_pure marginals byte-equal to m1. Currently bar2/bar3 in m7 are NOT byte-equal to m1; reweighting cherry should leave them undisturbed.

### 2.5 CV-RTP consistency (§5)

Per §5: higher RTP → lower CV. v7 trend (01b §1):
- m7 CV 7.07 > m1 CV 5.77 ✓ (CV_TREND_mode7_cv_ge_mode1 — cut mode boom-bust)
- m2 CV 5.14 < m1 5.77 ✓
- m5 CV 5.14 = m2 5.14 (base byte-identical lock)

**Design target band**: m1 base CV ∈ [3, 5] (user_brief #2). m7 CV ≥ m1 CV (philosophy §5). m2/m5 CV ≤ m1 CV. **m2/m5 base CV will move when m1 base CV moves** because m2 base RTP is 132.76pp vs m1 43.15pp — base shape changes shift both modes' CV in correlated ways. v0 design: keep direction lock; expect m2/m5 base CV to land ~4-5 when m1 base CV is ~4.

### 2.6 Family RTP share vs archetype baseline (§6)

01b §4 m1 family share-of-base:
- cherry1 31.91%, bar_mixed 20.77%, bar2 20.35%, bar3 9.70%, cherry2 8.22%, bar1 4.93%, high7_wild 2.76%, wild_pure 0.77%, cherry3 0.40%, high7_pure 0.21%

01d §3 archetype baselines:
- Cherry family (cherry-bearing classic IGT): **14-20%** of total RTP; M15 v7 cherry family (cherry1 + cherry2 + cherry3) = 31.91 + 8.22 + 0.40 = **40.53% of base** (= 18.39% of total) → at the high end of 14-20% archetype band ✓
- Bar family: 11-31% (RWB-style); M15 v7 bar family (bar1 + bar2 + bar3 + bar_mixed) = 4.93 + 20.35 + 9.70 + 20.77 = **55.75% of base** → above archetype upper bound. Because M15 uses mixed-bars combo (pay_id 8, 2× group payout) which the "bar 31%" archetype reference doesn't include — when bar_mixed is excluded, bar 3-of-a-kind = 34.98% (within band).
- 7-family / wild: archetype 30-70% (Blazing 7s 68.8%, RWB 45%); M15 v7 high7 + wild_pure = 2.76 + 0.77 + 0.21 = **3.74% of base** → **far below archetype lower bound**. Driven by user_brief #6 (jackpot ≤0.6%/reel) + jackpot filler design; high7 family suppressed.

**Per §6 ±15% archetype baseline tolerance**: M15's reduced 7-family is a **deliberate deviation** (per user_brief #5/#6 "avoid 1000+ wins" + "jackpot offsetting"). Must document in §4.

### 2.7 Top jackpot escalation (§7)

Per §7 universal direction: m1 1/50-100k → m7 1/50-100k → m2 1/15-30k → m5 1/3-10k.

01b §10 v7 top jackpot (pay_id 1 wild_pure, 200×):
- m1 1/60,141 → m2 1/7,401 → m5 1/7,401 → m7 1/56,070 ✓ direction holds.
- Ratio m5/m1 = 60141/7401 = 8.13× (philosophy requires ≥5× ✓)
- **But m5 cadence (1/7,401) is BELOW the §7 m5 floor "1/3,000-10,000"** — well within range, actually.
- **And m1 cadence (1/60,141) is within §7 m1 band "1/50-100k"** ✓.

**Per user_brief default decision: M15 explicit deviation from §7** — "M15 走密集 mid-high 替代稀有 top". This deviation is small (cadences are within §7 bands at the upper end) but the user_brief decision is to NOT chase a tighter "rare-top" cadence (e.g. 1/100k). **Design**: keep m1 top-jackpot cadence at v7 baseline (~1/60k), document deviation in §4 explicitly per process_improvements #9.

### 2.8 Hit decomposition (§8)

§8: any single pay_id hit / total hit ≤ 70%. v7 m1: cherry1 P=13.77%, total hit=19.31% → cherry1/total = 71.3% → **violation: cherry1 dominates 71% of hit** (just over §8 70% cap).

**Per user_brief default decision**: "cherry-1 1× anywhere is archetype necessity, accepted". Cherry-1 dominance is brand identity per §1.4 (cherry-anywhere mechanism standard in Top Dollar / RWB / Double Wild Cherry family).

**Design tension**: §8 cap vs §1.4 / user_brief cherry-archetype. Resolution: M15 takes accepted deviation from §8 (M15 is the "cherry-heavy classic" archetype, hit rate dominated by cherry1 by design). Verifier must add machine-specific carve-out in `verify.py` if §8 is implemented (otherwise it'll RED forever).

### 2.9 Mode-pair monotonicity (§9)

01b §11 v7 cross-mode invariants (all ✓ except MODE7_LOCK trigger which drifts 0.000454pp — see §3 below):
- mode2 RTP > mode1 ✓ | mode5 RTP > mode2 ✓ | mode7 RTP < mode1 ✓
- LUCKY_MONO mode2 hit > mode1 ✓ | mode5 hit ≥ mode2 ✓ | MODE7_LOCK m7 hit < m1 ✓
- MODE5_BASE_LOCK m5 base byte-equal m2 ✓
- CV trend m7 ≥ m1, m2 ≤ m1 ✓
- FEATURE m2 trigger ≥ m1 ✓ | m5 trigger ≥ m2 ✓

Feature-machine extension (§9): "mode 2/5 feature trigger rate ≥ mode 1" ✓; "Trigger-reel machines: mode 5 trigger symbol density ≥ mode 2" — m2 R3 topdollar 2.692% = m5 2.692% (equal per §C MODE5_BASE_LOCK — base byte-equal to m2, including R3 topdollar weight). Direction satisfied.

### 2.10 Pareto trap awareness (§10 + memory feedback_tuner_pareto_trap.md)

**Cherry-density vs hit-rate vs base-RTP-share interaction**:
- Cutting cherry1 → hit drops, but base RTP also drops (cherry1 currently 13.77pp). If cherry1 cut to P=10.5%, hit drops -3.27pp + base RTP drops -3.27pp = base 39.88pp → base:feature gets worse (38%/62% feature share!)
- To restore base 50:50, must offset cherry1 RTP drop by boosting other base pays (bar1/bar2/bar3 multiplier × frequency).
- Tuner may achieve numerical targets by:
  - **Pareto trap A**: cherry1 → cherry2/cherry3 (shifts to higher-payout cherries, frequency drops a lot, hit drops fast, but RTP per spin preserved). Result: cherry brand still hits, hit-rate target met, but bucket shape changes (ge1_lt5 share shrinks, ge5_lt10 grows). Player-perceived: "I'm not winning the small ones anymore".
  - **Pareto trap B**: cherry stays, bar_mixed gets cut hard (pay_id 8, 2× combo). Result: hit drops, RTP shifts to bar3 / bar2 lines. Player-perceived: "bars don't pay as often" — bar brand visibility damaged.

**Design defense per §10**: family RTP share floors (see §7 of this doc).

### 2.11 "假但不怪" axiom (§11)

Per §11: experience = soul; numbers passing ≠ done. v0 design narrative must answer: "what does a m1 player feel?" — see §5 mode-by-mode narrative.

### 2.12 Reel asymmetry §12 — R1 winners-friendly, R3 trigger

01b §6 v7 baseline (mode 1):
- R1 blank 54.50% / R3 blank 54.51% — essentially equal (Δ=+0.01pp); direction lock OK
- R1 top-prize density (doublediamond + high7) = 6.22%; R3 = 3.38% → Δ(R1-R3) = +2.84pp ✓ (R1 winners-friendly)

Modes 2/5 have **R3 blank LOWER than R1 blank by 10.45pp** (R3 = 24.23% vs R1 = 34.68%). This is because the lucky modes pile more topdollar weight onto R3 (m2/m5 trigger 2.69% vs m1 1.13%) and increase doublediamond/high7 weight on R3 too — displacing blanks. Direction lock is violated in v7 m2/m5 (`blank R1≤R3 direction ✓` is ✗). **Design tension**: §12.2 lock vs archetype "R3 trigger reel + lucky lift makes R3 winners-rich". Per philosophy §12.3 "Lucky modes (RTP > 200%): 容差应宽" — lucky modes legitimately relax R1<R3 blank.

**Per philosophy §12.4 tuner Pareto** + §12.2 universal direction "R1 ≤ R3 blank": Designer must mark this as a **machine-specific exception for lucky modes** (m2/m5). Verifier should NOT enforce R1 ≤ R3 blank for m2/m5; only enforce for m1/m7.

### 2.13 Blank-flank diversity (§13)

01b §8: 0 violations ✓. Strip is shared across modes (`reel_strips.json` `_invariants` row 1). **Design: do NOT touch reel_strips.json** — passes universal hard rule. Cite §13: "strip md5 改 → rawdata 失效".

### 2.14 Visual rhythm (§14)

M15 strip: 18 blanks + 18 non-blanks strict alternation. Visual rhythm via cross-symbol distribution. No per-machine §14 issue measured in 01b. **v0: keep current strip ordering**.

### 2.15 Window visibility / PWDF (§15)

Per §15.6 physical-reel: PWDF NOT in tune cost; post-tune redistribution if needed. v7 already has reasonable PWDF (any-reel max 15-17% for top symbols on physical 36-stop strip). **v0 design: no PWDF redistribute scheduled**; revisit if Stage 6 verify catches mid-pay visibility issue (mode 2/5 R3 PWDF drops since R3 has fewer blanks — 01b §7 cherry R3 mode 2 PWDF = 2.27 vs mode 1 R3 cherry PWDF = 4.91 — but Cherry is brand visibility floor, not "top symbol"). Documented as monitored, not actioned.

---

## 3. User brief response (truth layer 3)

Cite key: U#n = user_brief.md item n.

### 3.1 U#1 — Mode 1 hit ∈ [15%, 18%]

**Gap**: v7 19.31% → target [15, 18]. Cut −1.31pp to −4.31pp.
**Lever**:
- Cut bar_mixed P=3.86% → ~2.5% saves ~1.4pp hit.
- Trim cherry1 P=13.77% → 12.5% saves ~1.27pp hit (preserving cherry share-of-base ≥25% per pareto-trap defense, see §7).
- Net: target hit = 16.5% (mid of 15-18 band).
**Pareto check**: cherry1 cut from 13.77% to 12.5% = -9.2% relative; cherry1 RTP 13.77pp → 12.5pp = −1.27pp; need offset elsewhere or accept feature-share rebalancing.

### 3.2 U#2a — Base CV ∈ [3, 5]

**Gap**: v7 5.77 → target [3, 5]. Smooth −0.77 to −2.77 (target ~4.0 = midpoint).
**Lever** — see §5.2:
- Cut bar3 P=0.11% → ~0.08% (chops the ge20_lt50 + ge50_lt100 tail contribution).
- Cut high7_wild and wild_pure marginals slightly to reduce ge100_lt200 / ge200_lt500 tail.
- Restore some of the RTP via bar1 boost (5× hits keep base RTP up without extending tail).

### 3.3 U#2b — Feature CV ∈ [1, 2]

**Gap**: v7 0.74 → target [1, 2]. Widen +0.26 to +1.26.
**Lever** — see §5.4:
- Pull `x_value_weights` from [0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684] toward less concentrated distribution.
- Increase weight on value=1000 from 0.0001 → ~0.05 (still rare, but P(1000 drawn) goes from 0.001% to ~0.05% per round).
- Decrease weight on value=5 from 40.9684 each → ~25 each.
- Result: distribution spreads, P(R ≥ 200) lifts modestly, CV widens.

### 3.4 U#3 — Base:Feature 50:50 ±5pp

**Gap**: v7 45.4:54.6 → target 50:50. Shift +4.6pp from feature to base.
**Lever**:
- Combined effect of U#1 cherry cut (lowers base 1.3pp) + bar1/bar2 boost (raises base 5-6pp) → net base up ~4pp.
- Trigger rate cut from 1.127% to ~1.03% drops feature RTP by ~4.4pp (since EV stays 46×).
- Net: m1 base 47.5pp + feature 47.5pp ≈ 95% total ✓.

### 3.5 U#4 — P(count_x=1) ≤ 2%

**Gap**: v7 5.0% → target ≤2%.
**Lever**: `x_count_weights = (5, 40, 40, 12, 3)` → P(count_x=1) = 5/100 = 5%.
- Set to `(2, 40, 40, 14, 4)` (sum = 100) → P(count_x=1) = 2/100 = 2.0% ✓
- Or `(1, 40, 40, 15, 4)` → P=1% (more aggressive headroom)
- v0 chooses 2/100 = 2.0% (right at cap; more conservative; can tune up later).

### 3.6 U#5 — Avoid 1000×/spin across all modes (P ≤ 1e-5)

v7 baseline (01b §9):
- m1 P(R≥1000 per paid spin) = 1/4,809,365 = **2.08e-7** ✓
- m2 = 1/341,923 = **2.92e-6** ✓ (borderline, but ≤1e-5)
- m5 = 1/7,808,346 = **1.28e-7** ✓
- m7 = 1/4,807,429 = **2.08e-7** ✓

**Design constraint**: v0 changes to `x_value_weights` in m2 (lucky derivation) and m5 (super-lucky) must NOT push m2/m5 P(R≥1000 per spin) above 1e-5. Specifically:
- m2 currently borderline (2.92e-6); pulling more weight onto value=1000 in m2's `x_value_weights` could push it over.
- m5 has lots of headroom (1.28e-7) — can absorb x_value_weight shift toward big-x.

### 3.7 U#6 — Jackpot per-reel marginal ≤ 0.6% all modes

v7 (01b §5):
- m1 R1 0.08% / R2 0.53% / R3 0.14% — all ≤ 0.6% ✓
- m2/m5 R1 0.35% / R2 0.74% / R3 0.48% — **R2 = 0.74% violates 0.6%** ✗ ... wait, re-read 01b §5 m2 row: jackpot R2 = 0.743%. Yes that's a violation of user_brief #6 in v7.
- m7 R1 0.40% / R2 0.52% / R3 0.08% — all ≤ 0.6% ✓

**Design**: cut jackpot R2 weight in m2/m5 to bring marginal ≤ 0.6%. Since `jackpot` is decorative filler (spec `_notes` row 4), its weight is freely tunable — pure marginal-level constraint.

---

## 4. Deliberate deviations from archetype (must own these)

Per task brief contamination firewall: these deviations are M15-specific and must be documented; do NOT chase archetype baseline blindly.

### 4.1 Base CV [3, 5] vs RWB ~10

- **Archetype baseline (01d §7.2)**: RWB CV 10.4 (classic 3-reel 1-line).
- **M15 user_brief #2**: base CV [3, 5].
- **Why deviation**: M15 is a "modern low-vol base + mid-vol feature" hybrid, NOT classic 3-reel boom-bust. Per philosophy §5 + 01d §7.2 conclusion: "The 3-5 target is achievable only if base game is very low volatility (lots of small frequent wins)... deliberately repositions M15's base game away from classic high-vol toward a 'low-vol base + mid-vol feature' architecture."
- **Implication for verify**: do NOT use RWB CV 10 as red line; use brief band [3, 5]. Verifier should cite this section.

### 4.2 Base:Feature 50:50 vs classic 0-30% feature

- **Archetype baseline (01d §3.3)**: Classic Top Dollar bonus share undisclosed but likely 15-30% (Feature Play archetypes). RWB has 0% feature.
- **M15 user_brief #3**: 50:50 ±5pp.
- **Why deviation**: M15 is "Top Dollar with maximally featured architecture" — the feature is co-equal RTP source. Per 01d §3.3 final paragraph: "M15 is closer to Wheel of Fortune Top Dollar variants or modern 'feature-heavy' classics where the bonus is a co-equal RTP source".
- **Implication**: trigger rate 1/89 (much above industry median 1/191) is archetype-consistent **for this design choice**. Don't chase a lower trigger.

### 4.3 Multi-mode (lucky / super-lucky / cut)

- **Archetype baseline (01d §6.1)**: No "Lucky Top Dollar" SKU exists. Multi-mode is a virtual-machine / online-platform construct.
- **M15 user_brief implicit**: all 4 modes shipped (modes 1, 2, 5, 7).
- **Cross-game precedent**: Aristocrat Lucky 88 (player-selectable RTP 87.9-96.6% via Extra Choice feature, [AskGamblers](https://www.askgamblers.com/casino-games/online-slots/reviews/lucky-88-aristocrat) — HIGH) + operator-selectable Buffalo (88/90/92/94% RTP options, [Casino.org](https://www.casino.org/blog/return-to-player-decoded/) — HIGH).
- **Why deviation OK**: cross-mode is platform-level concept, not archetype. Each mode tuned per universal philosophy §4/§9/§C/D (mode-pair monotonicity + per-tier hit preservation + base byte-equal locks).

### 4.4 P(count_x=1) ≤2% — single-card-reveal is rare

- **Archetype baseline (01d §4.5)**: per-round single-offer is Top Dollar's design (1 card = 1 offer). M15's multi-card-per-round (count_x ∈ [1,5]) is a M15-specific addition to add per-round variance.
- **M15 user_brief #4**: ≤2%.
- **Why deviation**: with count_x ∈ [1,5] mechanic in place, single-card rounds feel stingy compared to 3-4 card rounds. ≤2% makes single-card rare event ("just one card — must be special") rather than common stinginess.
- **Note for Designer iterations**: if Stage 4 review wants count_x=1 to be common (Top Dollar archetype-faithful), revisit U#4 with user. Current v0 takes user_brief at face value.

### 4.5 Top jackpot cadence — m1 ~1/60k stays (dense mid-high, rare top)

- **Universal §7 baseline**: m1 1/50-100k = "lifetime story tier".
- **M15 user_brief default decision**: §7 deviation accepted; "M15 走密集 mid-high 替代稀有 top". m1 v7 ~1/60k cadence stays.
- **Why deviation**: 01b §10 shows m1 wild_pure 1/60,141 — exactly at the upper boundary of §7 m1 band. The deviation is "we will NOT chase tighter cadence" — design choice already inside band but not at the bottom.

### 4.6 R1 ≤ R3 blank lock relaxed for lucky modes (m2/m5)

- **Universal §12.2 (3-reel)**: R1 blank ≤ R3 blank.
- **M15 v7 m2/m5**: R3 blank 24.23% < R1 blank 34.68% → direction violated.
- **Why violation OK**: per §12.3 "Lucky modes (RTP > 200%): 容差应宽". R3 holds topdollar (3× more in m2/m5 vs m1) AND lucky-mode top-prize lift — R3 is winners-rich by archetype in lucky modes.
- **Verifier action**: enforce R1 ≤ R3 blank ONLY for m1/m7; relaxed (or reverse-direction OK) for m2/m5. Document in machines/M15/verify.py.

### 4.7 Cherry1 dominates hit (~71% of total hit) — §8 violation accepted

- **Universal §8**: any single pay_id ≤ 70% of total hit.
- **M15 cherry-anywhere mechanism**: per §1 / 01d §8 — cherry-1 1× anywhere is archetype-faithful and "structurally required" (user_brief default decision: do not change paytable).
- **Why violation OK**: cherry-1 is brand-identity pay for Top Dollar / RWB / Double Wild Cherry classic family. Removing it = breaks archetype.
- **Verifier action**: machine-specific carve-out — cherry1 share-of-hit allowed up to 80% (will measure exact share post-tune to confirm bound).

---

## 5. Mode-by-mode narrative

### 5.1 mode 1 (paid baseline)

**Player experience**: "Modern Top Dollar — base game is steady drip of small cherry/bar pays (15-18% hit rate, mostly $1-5 wins), feature triggers about 1 in 90 spins ($40-200 typical, occasional bigger). Volatility is even, not boom-bust."

**Target metrics**:
| metric | v7 | v0 target | source |
|---|---:|---:|---|
| Total RTP | 94.98% | 95.0% ±1pp | user_brief default + philosophy §C mode 1 invariant |
| Base RTP | 43.15pp | 47.5pp | user_brief #3 → 50:50 split @ 95% RTP |
| Feature RTP | 51.83pp | 47.5pp | user_brief #3 + EV=46× × trigger=1.03% derivation |
| hit_rate | 19.31% | 16.5% (band [15,18]) | user_brief #1 mid-band |
| base CV | 5.77 | 4.0 (band [3,5]) | user_brief #2a mid-band |
| feature CV (conditional) | 0.74 | 1.5 (band [1,2]) | user_brief #2b mid-band |
| trigger rate | 1.127% (1/89) | 1.03% (1/97) | derivation: feature RTP 47.5 / EV 46 = 1.03% |
| Feature EV | 46× | 46× | preserve v7 EV (user_brief #3 default) |
| P(count_x=1) | 5.0% | 2.0% | user_brief #4 cap |
| top-jackpot cadence | 1/60,141 | ≥1/65,000 floor | philosophy §7 m1 1/50-100k band + user_brief default deviation |
| P(R≥1000 / spin) | 2.08e-7 | ≤1e-5 | user_brief #5 |
| jackpot R1/R2/R3 marg | 0.08/0.53/0.14% | all ≤0.6% | user_brief #6 |

**Derivation (where do weights move from v7 baseline)**:
- **cherry density ↓**: cherry1 P 13.77% → 12.5% (cite 01b §3 m1 cherry1; user_brief #1 hit cut). cherry2 and cherry3 frequency unchanged.
- **bar_mixed cut**: bar_mixed P 3.86% → 2.5% (cite 01b §3 m1 bar_mixed; user_brief #1 hit cut; philosophy §10 pareto defense — small-pay cut, not high-pay cut).
- **bar1 boost**: bar1 P 0.25% → 0.50% (cite 01b §3 m1 bar1; philosophy §1 family hierarchy — bar1 (5×) should be MORE frequent than bar2 (10×); currently inverted).
- **bar2 trim**: bar2 P 0.58% → 0.42% (philosophy §1; offsets bar1 boost).
- **bar3 trim**: bar3 P 0.11% → 0.08% (cite 01b §3 m1 bar3; user_brief #2a CV cut — bar3 20× pays drive base tail).
- **high7_wild trim**: P 0.014% → 0.010% (cite 01b §3 m1 high7_wild; CV smoothing).
- **wild_pure preserve**: P 0.00166% → 0.00154% (preserve §7 m1 1/65k cadence; small trim consistent with low-vol shift).
- **feature trigger rate cut**: R3 topdollar marginal 1.127% → 1.03% (R3 topdollar 2 stops × 8 weight / total 1420 → 2 × 7.3 / total). Implementation: drop R3 topdollar weight per stop from 8 to ~7.3 (rounded integer; exact will iterate).
- **x_count_weights**: `(5, 40, 40, 12, 3)` → `(2, 40, 40, 14, 4)` (user_brief #4 cap; redistribute to count_x=4/5 to keep EV ~46×).
- **x_value_weights**: pull from `[0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684]` toward `[0.05, 0.5, 1.0, 1.0, 4.0, 4.0, 10.0, 10.0, 25.0, 25.0]` (user_brief #2b CV widen; preserve EV ~46×; verify P(R≥1000 per round) doesn't violate U#5 at m2/m5 lucky scale).

**Top-prize cadence**: m1 wild_pure ≥1/65k floor maintained (user_brief default decision).

### 5.2 mode 7 (cut)

**Player experience**: "Same base game character as mode 1, but small wins come less often (cherry-1 'every 9 spins' instead of every 7). Top wins and feature triggers feel just like mode 1. Net RTP 85% means longer dry spells."

**Target metrics**:
| metric | v7 | v0 target | source |
|---|---:|---:|---|
| Total RTP | 85.09% | 85.0% ±1pp | philosophy §C cut mode |
| Base RTP | 33.24pp | 37.5pp | derive: 85% − feature 47.5pp = 37.5pp |
| Feature RTP | 51.85pp | 47.5pp | **MUST = mode 1 feature** (§11 invariant `MODE7_LOCK feature_params byte-equal`) |
| hit_rate | 14.92% | 12.5% (band [11, 14]) | philosophy §4 m7 < m1 ratio; derive from m1 16.5% × (37.5/47.5) base-RTP ratio |
| base CV | 7.07 | 5.0 (band [4.5, 6]) | philosophy §5 m7 CV ≥ m1 CV (= 4.0); cut mode boom-bust adds variance |
| trigger rate | 1.127% (1/89) | **= mode 1 (1.03%)** | §11 MODE7_LOCK byte-equal + per process_improvements #8 fix path |
| Feature EV | 46× | **= mode 1 (46×)** | §11 MODE7_LOCK feature_params byte-equal |
| feature CV | 0.74 | **= mode 1 (1.5)** | §11 byte-equal |

**Derivation rules** (per philosophy §4 cut mode):
- Cut small-pay frequencies (cherry1, bar_mixed) — multiplier ~0.80 to ~0.85 of m1 frequency (smaller than v7 cut ratio because base RTP target is now 37.5pp not 33.24pp).
- Preserve mid-pay frequencies (bar1, bar2, bar3) byte-equal to m1 — per §4 "中/大/顶奖 hit 不动".
- Preserve top-pay (wild_pure, high7_wild, high7_pure) byte-equal to m1.
- **CRITICAL: R3 topdollar weights byte-equal to m1** — fix v7 0.000454pp drift documented in process_improvements #8. Per user_brief: "mode 7 = mode 1 砍小奖 freq, feature_params 字节级 = mode 1". This includes R3 topdollar stop weights (which set the trigger rate), not just `feature_params` in weights.json.
- `feature_params` block byte-equal to m1 (x_count_weights, y_count_weights, x_value_weights, y_value_weights, accept_threshold, max_rounds all identical).

### 5.3 mode 2 (lucky)

**Player experience**: "Lucky 88-style RTP-uplifted mode — base game hits 1.5× as often (29% vs 19%, the dice favor you), feature triggers 2.4× more often (every 37 spins vs every 89). Bigger feature payouts on average. Player narrative: 'today's a lucky day'."

**Target metrics**:
| metric | v7 | v0 target | source |
|---|---:|---:|---|
| Total RTP | 294.28% | 300% ±5pp | philosophy §C mode 2 invariant |
| Base RTP | 132.76pp | 150pp | derive: lucky lift × base proportion |
| Feature RTP | 161.52pp | 150pp | derive: 300 − base 150 |
| hit_rate | 29.35% | 26.4% | user_brief default: "hit ×1.5-2"; 16.5 × 1.6 = 26.4 mid-range |
| base CV | 5.14 | 4.5 (band [4, 5.5]) | philosophy §5 m2 CV ≤ m1 CV (4.0) — but m2 base RTP 150pp means CV math differs |
| trigger rate | 2.692% (1/37) | 2.45% (1/41) | derive: feature RTP 150 / EV 61.2 = 2.45% |
| Feature EV | 60.0× | 61.2× | preserve approx v7 EV; slight lift |
| feature CV | 0.78 | 1.5 (band [1, 2]) | user_brief #2b — same target across modes per design intent |
| P(R≥1000 / spin) | 2.92e-6 | ≤1e-5 | user_brief #5 |
| jackpot R2 marg | 0.743% | ≤ 0.60% | user_brief #6 (v7 violates; fix) |

**Cross-mode invariants** (philosophy §5 + §9 + §C):
- mode 2 base ≠ mode 1 base (m2 base RTP must be higher per LUCKY-MONO).
- mode 5 base = mode 2 base BYTE-EQUAL (§C invariant — non-negotiable).
- mode 2 trigger ≥ mode 1 trigger (§9 feature-machine extension).
- mode 2 R3 topdollar density ≥ mode 1 R3 topdollar density (per §9 trigger-reel machines).

**Derivation rules**:
- Boost cherry / bar / high7 marginals across all reels (per philosophy §4 lucky mode "所有 tier hit 都略升").
- Reduce blank weights — R1/R2/R3 blank ~34-35% baseline (v7 already this).
- **Fix jackpot R2 marg** — cut jackpot weight on R2 from current value (whatever produces 0.74%) down to ≤0.6% target. Verify across modes 2/5 (same base bytes).
- Feature params (per-mode `feature_params` block in `weights/mode_2/weights.json`):
  - `x_count_weights` mirror mode 1 (count_x=1 → 2%) **or** lift count_x slightly for higher EV.
  - `x_value_weights` shift slightly upward (more weight on value=20/50/100) to lift EV from 46× to ~61× — but cap to ensure P(R≥1000/round) doesn't violate U#5 at trigger rate 2.45%.
  - `y_count_weights`/`y_value_weights` per design intent. (y is multiplier ×2, ×2; affects variance not EV.)

### 5.4 mode 5 (super-lucky)

**Player experience**: "Same lucky-base as mode 2 (29% hits, no different paytable shape there), but feature is BUFFED — bigger payouts more often. Feature trigger same rate as mode 2 (1/37). When feature triggers, expect 50-200× more often than mode 2's typical 50-100×. RTP 500%."

**Target metrics**:
| metric | v7 | v0 target | source |
|---|---:|---:|---|
| Total RTP | 490.32% | 500% ±5pp | philosophy §C mode 5 invariant |
| Base RTP | 132.76pp | 150pp | **MUST = mode 2 (BYTE-EQUAL)** (§C MODE5_BASE_LOCK) |
| Feature RTP | 357.56pp | 350pp | derive: 500 − base 150 |
| hit_rate | 29.35% | 26.4% | **MUST = mode 2** (base byte-equal) |
| base CV | 5.14 | 4.5 | **MUST = mode 2** (base byte-equal) |
| trigger rate | 2.692% (1/37) | 2.45% (1/41) | **MUST = mode 2** (R3 topdollar weight bytes-equal via base byte-equal) |
| Feature EV | 132.8× | ~143× | derive: 350 / 2.45% = 143× |
| feature CV (conditional) | 0.86 | 1.5 (band [1, 2]) | user_brief #2b |
| P(R≥1000 / spin) | 1.28e-7 | ≤1e-5 | user_brief #5 (m5 has lots of headroom) |

**Cross-mode invariants**:
- mode 5 base BYTE-EQUAL mode 2 base (§C — non-negotiable; verified 01b §11 ✓ in v7).
- mode 5 feature EV > mode 2 feature EV (philosophy §7 top-jackpot escalation, §9 mode 5 super-lucky).
- mode 5 top-jackpot cadence (wild_pure 1/N) should be more frequent than m2 (m5/m2 cadence ratio achieved via base byte-equal AND feature distribution shifted upper — top jackpot lift comes from feature side, not base).
- Wait — top jackpot pay_id 1 (wild_pure 200×) is a BASE pay, not feature. So base byte-equal means m5 and m2 wild_pure cadence are IDENTICAL (m2 = m5 = 1/7,401 per 01b §10). **m5/m2 top-jackpot escalation in M15 comes from FEATURE side** (P(feature R ≥ some big threshold) lifts with feature buff).
- This is a M15-specific reading of §7: the "top jackpot" is the feature's high-payout tail, not the base wild_pure pay. Document this in DESIGN.md.

**Derivation rules**:
- Base weights **byte-equal to mode 2** — copy verbatim from mode 2 weights.json after mode 2 lock.
- Feature params (per-mode `feature_params` block in `weights/mode_5/weights.json`):
  - `x_count_weights` shift upper (more 3-card / 4-card / 5-card rounds): EV ↑.
  - `x_value_weights` shift upper substantially (more weight on value=50, 100, 1000): EV ↑ + tail expanded.
  - `y_count_weights` shift toward count_y=2 (×4 multiplier): EV ↑.
  - **Verify P(R≥1000/spin) at trigger 2.45% × P(R≥1000|trigger) ≤ 1e-5**: with trigger 2.45%, need P(R≥1000|trigger) ≤ 1e-5 / 0.0245 = 4.08e-4 (~0.04% per trigger). v7 m5 has P(R≥1000|trigger) = 0.00048% — plenty of headroom to lift to ~0.04% if needed. **EV lift to 143× via shifted distribution is feasible without violating U#5**.

---

## 6. Targets per mode (summary table)

| metric | mode 1 | mode 2 | mode 5 | mode 7 |
|---|---:|---:|---:|---:|
| Total RTP | 95.0% ±1pp | 300% ±5pp | 500% ±5pp | 85.0% ±1pp |
| Base RTP | 47.5pp | 150pp | =m2 (150pp) | 37.5pp |
| Feature RTP | 47.5pp | 150pp | 350pp | =m1 (47.5pp) |
| Base:Feature split | 50:50 ±5pp | 50:50 ±5pp | 30:70 ±5pp | 44:56 ±5pp |
| hit_rate (base) | 16.5% [15,18] | 26.4% [25,28] | =m2 [25,28] | 12.5% [11,14] |
| base CV | 4.0 [3,5] | 4.5 [4,5.5] | =m2 [4,5.5] | 5.0 [4.5,6] |
| feature CV | 1.5 [1,2] | 1.5 [1,2] | 1.5 [1,2] | =m1 [1,2] |
| trigger rate | 1.03% (1/97) | 2.45% (1/41) | =m2 (1/41) | =m1 (1/97) |
| feature EV | 46× | 61× | 143× | =m1 (46×) |
| P(count_x=1) | 2.0% | 2.0% | 2.0% | =m1 (2.0%) |
| top-jackpot cadence (wild_pure 200×) | ≥1/65k | ≥1/8k (=m5) | ≥1/8k (=m2) | ≥1/55k |
| P(R≥1000 / spin) | ≤1e-5 | ≤1e-5 | ≤1e-5 | ≤1e-5 |
| jackpot per-reel marg | ≤0.6%/reel | ≤0.6%/reel | =m2 ≤0.6% | ≤0.6%/reel |

**Note on m7 hit-rate band**: derived as m1_hit × (m7_base_RTP / m1_base_RTP) = 16.5 × (37.5/47.5) = 13.0% midpoint. Band [11, 14] gives ±1.5pp room. Verifier may need to widen if cherry / bar_mixed multiplicative cuts at desired ratios collide with §1 hierarchy gap.

---

## 7. Family RTP share bands (Pareto-trap defense per philosophy §10)

**Per philosophy §10 + memory `feedback_tuner_pareto_trap.md`**: each critical family gets a share-of-base floor in tune cost.

### 7.1 Mode 1 family share-of-base floors

| family | v7 share-of-base | v0 floor | source |
|---|---:|---:|---|
| cherry1 | 31.91% | ≥25% (cap ≤40%) | archetype-necessary (user_brief default + §1.4 cherry-anywhere) |
| cherry family (cherry1+2+3) | 40.53% | ≥30% (cap ≤50%) | archetype 14-20% of TOTAL = 30-42% of base (95% RTP) — band derived |
| bar_mixed | 20.77% | ≥10% (cap ≤25%) | mid-pay broad reach; pareto-trap risk if tuner cuts to zero |
| bar 3-of-kind (bar1+2+3) | 34.98% | ≥25% (cap ≤45%) | archetype RWB bar 31%; classic 11-31% band; M15 floor at 25% |
| bar1 (5×) | 4.93% | ≥3% (cap ≤10%) | philosophy §1 — bar1 frequency floor (lower payout = higher frequency) |
| bar2 (10×) | 20.35% | ≥10% (cap ≤25%) | philosophy §1 — bar2 frequency between bar1 and bar3 |
| bar3 (20×) | 9.70% | ≥5% (cap ≤15%) | philosophy §1 — bar3 lowest of bar family |
| high7 (wild + pure) | 2.97% | ≥2% (cap ≤8%) | archetype 30-70% TOO HIGH for M15 because doublediamond wild absorbs share; high7 floor 2% to maintain brand visibility |
| wild_pure (200×) | 0.77% | ≥0.4% (cap ≤2%) | top-jackpot brand pay; §7 top-jackpot escalation depends on this |

### 7.2 Mode 7 family share-of-base floors (cut mode)

Same family floors as m1 but scaled by m7/m1 base RTP ratio (0.79). Per-tier preservation per philosophy §4 (small cuts, mid/top unchanged):
- cherry1 cut allowed (33.08% v7 → can drop further); floor ≥22%
- bar_mixed cut allowed; floor ≥8%
- bar1/bar2/bar3 byte-equal to m1 (preserved per §4)
- high7 / wild_pure byte-equal to m1 (preserved per §4)

### 7.3 Mode 2 / Mode 5 family share-of-base floors

m5 base = m2 base byte-equal (§C). m2 family shares are derived from m2's base RTP (150pp) — proportional to v7 m2 shares (which are 18-21% bar3/2 + 16.6% high7_wild + 11.6% cherry1 + ... per 01b §4 m2). v0 maintains v7 m2/m5 family structure; lucky mode lifts marginals uniformly per philosophy §4 ("所有 tier hit 都略升").

**Floors are guidance — tuner enforced**: cost function must penalize share dropping below floor (linear above floor, quadratic below). Avoids pareto trap A/B from §2.10.

---

## 8. Open design questions (Designer can't resolve unilaterally)

### 8.1 [LOW PRIORITY] count_x=1 cap mechanism direction

Per 01d open #1: archetype is per-round single-offer (1 card = 1 offer). M15's multi-card mechanic adds variance. user_brief #4 cap ≤2% — Designer interprets this as "single-card is rare". Alternative reading: count_x=1 should be the COMMON mode (matching archetype) and 2-5 cards rare. **Resolution path**: take user_brief #4 at face value (≤2%); flag if Stage 4 review wants reconsideration.

### 8.2 [MEDIUM PRIORITY] feature distribution widening at m2 borderline of U#5

v7 m2 P(R≥1000 / spin) = 2.92e-6 (within ≤1e-5 cap). Pulling x_value_weights upper for feature CV widening (U#2b) could push m2 toward the cap. **Resolution path**: explicit verify red line at m2 P(R≥1000/spin) ≤ 1e-5 (band of safety: target ≤5e-6 to keep headroom). Designer recommends Verifier writes a TIGHT m2 cap; m5 has plenty of room.

### 8.3 [MEDIUM PRIORITY] top-jackpot escalation in M15 — base vs feature

§7 universal expects m5 top jackpot frequency > m2 > m1. In M15, the **base** wild_pure (pay_id 1, 200×) cadence is IDENTICAL across m2 / m5 (byte-equal base). So §7's top-jackpot escalation MUST come from FEATURE side (P(feature R big) lifts m5 > m2).

**Resolution path**: Designer reads §7 with M15 carve-out: the "top jackpot" for cross-mode escalation in M15 is the feature's tail (e.g., P(feature R ≥ 500/spin)), not the base wild_pure. Document explicitly + cite in Verifier red-line.

### 8.4 [LOW PRIORITY] reel_strips changes

01b §6: m1 R1=R3 blank approx (Δ=0.01pp). m2/m5 R1>R3 blank (lucky-mode trigger-displacement). No §13 violations. **Resolution**: do NOT touch reel_strips.json in v0; weights tune only. Cite §13 strip-md5 risk.

### 8.5 [HIGH PRIORITY] MODE7 trigger byte-equal definition

process_improvements #8 surfaced: user_brief says "feature_params 字节级 = mode 1". Does this mean:
- (a) `feature_params` BLOCK byte-equal (x_count_weights / y_count_weights / x_value_weights / y_value_weights / accept_threshold / max_rounds identical) — DOES NOT touch R3 topdollar weights;
- (b) Both `feature_params` block AND R3 topdollar weights byte-equal (so trigger rate IS literally equal, not just marginally-equal).

v7 has (a) but NOT (b) — R3 topdollar weights are 8/8 in m1 (R3 total 1420) and 7/7 in m7 (R3 total 1242). Marginal: m1 = 1.1268%, m7 = 1.1272% — drifts 0.000454pp.

**Designer's reading**: user_brief intent is (b) — "byte-equal" means literal byte equality, which forces R3 topdollar weights equal. Otherwise the invariant is "marginal-equal" not byte-equal.

**Resolution path**: v0 design enforces (b). R3 topdollar weights in m7 weights.json MUST byte-match m1 (same per-stop integer weights). Verifier checks raw byte equality, not just marginal closeness.

### 8.6 [LOW PRIORITY] schedule mode 5 / mode 7 target files

Modes 5 / 7 are derived from modes 2 / 1 via byte-equal locks + per-mode rules. Targets are NOT independent design intents — they are functions of the parent mode target + a transform rule. **Resolution**: only ship targets_v0/mode1_target.json + mode2_target.json (which require independent design). Mode 5 / Mode 7 specifications captured in this design_v0.md §5.4 / §5.2 + cross-mode invariants in §6; Verifier constructs verify.py red lines from those.

---

## 9. Citation manifest

Each numeric target in §3 / §5 / §6 / §7 cites one of:

| Source code | Description | Examples |
|---|---|---|
| `R-archetype-URL` | 01d_research.md citation with URL | RWB CV 10.4, Strip $1 ~92%, DTD 96.24% |
| `A-measure` | 01b_baseline_report.md measured number | v7 cherry1 P=13.77%, v7 base CV 5.77 |
| `U#n` | user_brief.md item | U#1 hit [15,18], U#3 50:50 |
| `§N` | DESIGN_PHILOSOPHY.md section | §C mode RTP invariants, §4 cut mode rules |
| `processimp#n` | process_improvements.md entry | #8 MODE7 trigger drift fix |

**Numbers in this doc that lack a citation are bugs — must be cited or removed before Stage 4 review.**

Spot-check a few:
- "mode 1 RTP 95%" — §C (philosophy mode RTP invariant) + user_brief default decision (1.b)
- "mode 1 hit 16.5%" — U#1 mid-band [15, 18]
- "cherry1 P 12.5%" — A-measure baseline 13.77% (01b §3) − U#1 derivation (−1.27pp to hit cap 18% upper); rounded to drop ~1.3pp hit
- "feature EV 46×" — A-measure v7 (01b §1) + U#3 default decision (don't change EV; only trigger)
- "trigger 1.03%" — derivation from U#3 50:50 + EV=46×: feature RTP 47.5pp = 46 × trigger → trigger = 47.5/46 / 100 = 1.033%
- "P(count_x=1) 2.0%" — U#4 cap ≤2.0%; chose right at cap
- "x_value_weights [0.05, 0.5, 1.0, 1.0, 4.0, 4.0, 10.0, 10.0, 25.0, 25.0]" — derived from U#2b feature CV widen target ~1.5; preserves EV 46× via distribution shape; exact values are Designer proposal for Stage 5/6 tune init, not fixed target
- "R3 topdollar mode 7 = mode 1 byte-equal" — processimp#8 + §11 MODE7_LOCK_trigger_equal_to_mode1 (currently RED in 01b §11)
- "jackpot R2 m2 ≤0.6%" — U#6 + A-measure 01b §5 m2 R2 jackpot 0.743% (current violation)

---

## 10. Process improvements log addendum (D session)

(Will be appended to `process_improvements.md` after this doc lands. Below = preview of new entries.)

### #13 — `target_profile.py` schema is extract-only, not author-mode

`core/tuner/target_profile.py` extracts a target from an analyzer report (`extract_target(summary)`). It does NOT define a schema for **authoring** new targets (the Designer's use case at Stage 4). Designer at Stage 4 needs to author targets that capture **band ranges + family floors + cross-mode invariants** — fields not present in `extract_target` output.

**Workaround applied**: targets_v0/M15_mode{1,2}_target.json conform to the `extract_target` field set as much as possible BUT add a `_design_targets` block with bands, family floors, and cross-mode lock references (clearly marked as Designer authored, not extracted).

**Fix for ONBOARDING_PROCESS.md / target_profile.py**: split into two schemas. (a) `MeasurementProfile` = extract_target output (analyzer snapshot). (b) `DesignTarget` = Designer-authored bands + floors + invariants + reference to MeasurementProfile-style point target. The tuner cost function reads `DesignTarget`; Designer-authored band ranges become cost function bounds. Out-of-scope for M15 v0 — flag for refactor.

### #14 — `_design_targets` Designer-authored block conflicts with `_tuned_summary` contamination warning

process_improvements #2/#3 warn against reading historical narrative blocks (`_tuned_summary`, `_design`, `_notes`, `_weights_rationale`). Designer's authored `_design_targets` block in targets_v0/ would be contamination for the NEXT machine if a future Designer reads it expecting fresh data. **Recommendation**: prefix with `_design_targets_v0_M15_only` so it's obvious the block is M15-specific and Designer-authored, not a portable schema.

### #15 — User_brief #6 violation in v7 m2 jackpot R2 (0.743%) — first surfaced in D session

01b §5 reports v7 m2 / m5 jackpot R2 marginal at 0.743%. user_brief #6 says "保持任一 reel marginal ≤ 0.6%". v7 violates U#6 for m2/m5 R2. process_improvements should note this is a current v7 issue requiring fix in v0 redesign — not a new design intent.

**Fix for process_improvements.md**: add this finding so future Stage 4 reviews / Verifier setup don't miss it.

---

## End of design_v0.md

> **Next**: targets_v0/M15_mode1_target.json + targets_v0/M15_mode2_target.json + process_improvements.md update. Stage 4 review by X (Critic): 5 adversarial questions on this narrative + cite check on every number.
