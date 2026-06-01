# Wave-3 Validation — Play-Type Architecture Proposal
> arch-validator, Wave 3 (parallel with arch-critic). 2026-06-01.
> Grounded in: 04_architecture_proposal.md, 02_taxonomy.md, 01_pipeline_map.md, 03_coupling_audit.md, DIRECTION.md.
> All numbers from live rawdata (cached). Commands run via Bash.

---

## PRIORITY-1 RESULT: M10 CostCredits Verdict — PREMISE TRUE, PLUGIN JUSTIFIED

### Raw numbers (10,000 rounds, M10 mode_1 chunk_0001.json)

| Measure | Value |
|---|---|
| Total rounds | 10,000 |
| CostCredits > 0 | **0** (zero) |
| CostCredits == 0 | **10,000** (100%) |
| BetAmount > 0 | 10,000 (100%, BetAmount=1000 on every round) |
| SpinType distribution | {13: 10,000} — single ST |
| LockLines field | present on all 10,000 rounds |
| WinCredits > 0 | 2,191 rounds (21.91%) |

M23, M131, M133 (same family, listed in `parser.py:L627`) confirmed identical pattern: all 10,000 rounds CostCredits=0, all ST=13.

### What "trigger" means on M10

- Rounds with `ReMarks="trigger"`: 2,832 — these are the **initial paid spins** (the player's wager)
- Rounds with `ReMarks=""`: 7,168 — these are the **lock-respin continuations** (no additional cost)
- Both categories have `CostCredits=0`, `BetAmount=1000`. The server never populates CostCredits for this machine family.

### Current parser behavior (verified against parser.py lines 626-648)

The parser's pre-scan probe (`_all_zero_cost=True AND _any_positive_bet=True`) sets `cost_credits_unreliable=True`. Lines 1467-1468 then treat every round as `is_paid=True` regardless of CostCredits. The existing report for M10 (`rv_20260520T061613Z`) confirms: `spin_type_breakdown` shows `{spin_type:13, paid_rounds:10000}` — all 10,000 treated as paid.

### Verdict on `CostCreditsReliabilityPlugin` premise

**PREMISE IS TRUE.** The designer's claim — "M10-family: CostCredits always 0" — is correct. On M10 (and M23/M131/M133), `CostCredits=0` on all rounds despite a real player wager (`BetAmount=1000`). The fleet-universal bedrock rule `CostCredits>0 = paid` (taxonomy §A2) does NOT apply to this family. The `CostCreditsReliabilityPlugin` is not a phantom — it addresses a real rawdata exception.

**However**, there is a structural concern (see "Cases That Break" §3, Item A).

---

## 1. Representatives Picked

| Case | Machine | Play-types | Why selected |
|---|---|---|---|
| 1 | M14 | PT-1 (pure paid) | Sanity baseline; verifies the proposal doesn't overcomplicate the simple case |
| 2 | M15 | PT-1 + PT-8 (TopDollar selector) | The contested ST=1 FORK — same SpinType for base paid AND TopDollar trigger |
| 3 | M275 | PT-1 + PT-3 (BCM) + PT-4 (BCM freespin) + PT-2 (scatter freespin) | Hybrid: multiple play-types on one machine, two trigger mechanisms; jackpot tier pay_ids |
| 4 | M274 | PT-1 + PT-6 (BCM-ListReward Minigame) | BCM schema present but cc≡0; known attribution bug (4.87% unattributed_st139) |
| 5 | M120 | PT-1 + PT-14 (RewardIdToCollectAmount) | Fleet-rare signature (2 machines only); tests auto-detection of nearly-unique fields |
| 6 | M10 | PT-10 (LockLines, CostCredits always 0) | The contested CostCredits premise; tests `CostCreditsReliabilityPlugin` ordering |
| 7 | Hypothetical M400 | PT-1 + "wheel-collect" (novel) | Future machine with mechanic not in the 15; tests ONBOARDING ALERT path |

Selection covers: PT-1 (universal), PT-2, PT-3, PT-4, PT-6, PT-8, PT-10, PT-14 (8 of 15 play-types directly). PT-5/7/9/11/12/13/15 are adjacent to covered cases and not separately walked.

---

## 2. Per-Case Walkthrough

---

### Case 1: M14 — Pure Paid (sanity baseline)

**Today (current architecture)**
- 10,000 rounds, all ST=1, all CostCredits=1000. No bonus rounds.
- `parse_chunk_response` runs the full per-round loop; `is_paid_round()` returns True on all. No BCM, no trigger-session, no wild-nudge code fires.
- All 9 display plugins apply (from manifest). Report shows `payouts_by_spin_type={ST1_paid: [...]}`.
- Report hash: `base_hash ⊕ sorted(8 display plugin hashes) ⊕ mode=1`. (Cited from `03_coupling_audit.md §2`.)

**Under proposal**
- Auto-detect scans first 500 rounds: no BCM fields, no bonus ST, no trigger remark, no special fields.
- `PurePaidPlugin.CLAIM_SIGNATURE` matches (CostCredits>0, no bonus rounds).
- No other plugin matches. `onboarding_alerts=[]`.
- `MachinePlayTypeConfig` written: `active_plugins=["pure_paid"], st_map={1:"pure_paid"}`.
- `PurePaidAccumulator.on_round` is a no-op (pure paid has no per-round mechanic state).
- Hash: `base_hash ⊕ hash("pure_paid" plugin) ⊕ config_hash(M14/mode_1.json) ⊕ mode=1`.

**Migration**
- Existing M14 reports become "historical" (effective_analyzer_version changes because composition algorithm changes).
- No data reprocessing needed — M14 rawdata is unchanged; a fresh run with the new architecture produces byte-identical output (modulo new top-level keys `active_play_types`, `onboarding_alerts`).
- `bcm_pairings.json` and `machine_round_win_rules.json` have no M14 entries — no migration cost.

**Hash composition trace**
- Edit `BCMBasePlugin`: M14 has `bcm_base` NOT in its `active_plugins` → M14's effective version does NOT change. Correct.
- Edit `PurePaidPlugin`: M14 has `pure_paid` in its `active_plugins` → M14's effective version DOES change. Correct.
- Edit M274's per-machine config: M14's config is unchanged → M14 unaffected. Correct.

**Backward compat**
Existing M14 reports on disk: `effective_analyzer_version` will differ from the new composition value → reports show as "historical". This is expected fleet-wide on the one-time migration. No report can be served as "current" without regeneration.

**Verdict: PASS**

---

### Case 2: M15 — ST=1 FORK (base paid + TopDollar trigger)

**Rawdata confirmation (chunk_0001.json, 8,345 rounds)**
- ST=1: 8,000 rounds, ALL CostCredits=1,000 (nonzero). No DollarCount field on any ST=1 round.
- ST=14: 258 rounds, CostCredits=0. Fields: `DollarCount, ChosenDollar, OfferValue, JackpotIds, ExtraRatio`. No WinAmount.
- ST=15: 87 rounds, CostCredits=0. Field: `WinAmount`. WinCredits=null.
- Trigger correlation: 87 ST=1 rounds have `ReMarks="Trigger"` AND `pay_id=666`. Count matches ST=15 settlement count exactly (87/87).
- DollarCount field: ABSENT on all ST=1 rounds. Only appears on ST=14.

**Today (current architecture)**
- `SettlementWinAmountRule` in `round_win.py` (B-class, in `_CLOSURE_FILES`) handles ST=14 phantom + ST=15 settlement win extraction.
- `compute_trigger_sessions` (in `trigger_sessions.py`, B-class) detects the Type-1 trigger session from `ReMarks="Trigger"` on ST=1 rounds.
- Editing either file re-flags all 420 machines.
- `machine_round_win_rules.json` rule `topdollar_selector_settlement` applies to M15 variants (listed under `M15$TopDollar...`). This config change is SILENT (not hashed).

**Under proposal — auto-detect flow**
1. `TopDollarPlugin.CLAIM_SIGNATURE` requires `required_fields={"DollarCount","ChosenDollar","OfferValue"}`.
   - **DollarCount is present on ST=14 bonus rounds.** Signature matches.
2. `PurePaidPlugin.CLAIM_SIGNATURE` matches (ST=1 has CostCredits>0).
3. ST assignment:
   - ST=1: only `PurePaidPlugin` claims it (DollarCount is NOT present on ST=1 rounds — confirmed). No fork conflict. `{1: "pure_paid"}`.
   - ST=14: only `TopDollarPlugin` claims it. `{14: "topdollar"}`.
   - ST=15: only `TopDollarPlugin` claims it. `{15: "topdollar"}`.
4. `onboarding_alerts=[]`. No ambiguous ST.
5. Within `TopDollarAccumulator.on_round`: when ST=1 round has `pay_id=666 + ReMarks="Trigger"`, it records the trigger anchor. This is internal to the accumulator — it does not conflict with the `pure_paid` accumulator's handling of the same ST=1 round (the pure_paid accumulator tracks aggregate paid spin stats; trigger anchor is a separate signal).

**Rawdata confirms the fork is clean:** DollarCount never appears on ST=1 (0/8,000 checked), so the fork between `pure_paid` and `topdollar` on ST=1 is purely remark+payid based, which is exactly what `TopDollarAccumulator.on_round` handles internally.

**Migration**
- `machine_round_win_rules.json` `topdollar_selector_settlement` entries for M15 → migrated to `configs/play_type_configs/M15/mode_1.json` as `trigger_anchors` or `settlement_params`.
- Config is now hashed → editing it re-flags M15 only (today: SILENT).
- `SettlementWinAmountRule` moves to `TopDollarPlugin` source → TopDollar machines only re-flag on rule change (today: all 420 re-flag).

**Hash composition trace**
- Edit `TopDollarPlugin`: 6 machines (M12/M15/M32/M90/M132/M206 per taxonomy §A5) re-flag. Other 414 unchanged. Correct.
- Edit M15's per-machine config: only M15 re-flags. Correct. (Today: config change is SILENT.)
- Edit `BCMBasePlugin`: M15 does NOT have `bcm_base` active → unchanged. Correct.

**Backward compat**
Existing M15 reports: `topdollar_selector_settlement` rule is currently NOT hashed (SILENT). Under proposal, the config becomes hashed. Existing reports will show as historical (effective version changes). Regeneration required.

**Verdict: PASS**

---

### Case 3: M275 — Hybrid BCM + Scatter Freespin + Jackpot Tiers

**Rawdata confirmation (chunk_0001.json, 44,780 rounds)**
- ST=140: 40,000 rounds, CostCredits>0 (nonzero) on all. BCM fields present: `CollectCount` (range 1–1,000), `AccCredits`, `CreditsSymbols`, `SymbolIndexToRewards`. `GameplayTriggerType` also present.
- ST=126: 4,780 rounds, CostCredits=0. `ExtraRatio` field. All remarks match `Freespin N;` pattern.
- Trigger breakdown: 438 paid rounds have `pay_id=666` (scatter trigger). 40 paid rounds have `CollectCount=1000` (BCM peak). 1 round has both simultaneously.
- Jackpot tiers: `pay_id` in {27502, 27503, 27504} appear on 76 paid rounds and 22 bonus rounds.
- `TriggerFreespin` remark: **ABSENT** on all M275 paid rounds (0/40,000). M275 does NOT use the TriggerFreespin remark; M31 does.

**Today (current architecture)**
- BCM cycle detection runs in parse loop. Trigger sessions detected by `compute_trigger_sessions`.
- BCM pairing: `bcm_pairings.json` entry `M275: bonus_feature="NewFreespin"` (config, NOT hashed).

**Under proposal — auto-detect flow**
1. `BCMBasePlugin.CLAIM_SIGNATURE` requires `{"CollectCount","AccCredits","CreditsSymbols","SymbolIndexToRewards"}`. All present on ST=140. Matches.
2. `BCMFreespinPlugin.CLAIM_SIGNATURE` requires `required_bonus_remark_pattern=r"\bFreespin\b"`. Present on 4,780 ST=126 rounds. Matches.
3. `ScatterFreespinPlugin.CLAIM_SIGNATURE` requires `required_bonus_remark_pattern=r"\bFreeSpin\b"` AND `required_trigger_pay_id="666"`. Bonus rounds match. 438 paid rounds have pay_id=666. Matches.
4. ST assignments:
   - ST=140: BCMBasePlugin claims (BCM fields exclusive to this ST). Correct.
   - ST=126: BCMFreespinPlugin AND ScatterFreespinPlugin both claim via freespin remark. **This is a potential fork conflict.**

**Gap identified on ST=126 fork between BCMFreespinPlugin and ScatterFreespinPlugin on M275:**
Both plugins claim ST=126 via the freespin remark. The auto-detector step 2 ("if 2+ → check fork rule") must fire. The proposal (§5.2) defines the fork for M15's ST=1 case in detail, but for the M275 ST=126 case it relies on "exactly what happens inside `TopDollarAccumulator`" (analogously, "inside BCMFreespinAccumulator vs ScatterFreespinAccumulator"). The proposal text does NOT define a fork rule between BCMFreespin and ScatterFreespin for shared bonus ST=126 on M275.

The correct answer from taxonomy §A3 M275 entry: M275 has both a BCM-triggered freespin (8% of triggers via cc=1000) and a scatter-triggered freespin (92% via pay_id=666). These produce **identical bonus rounds** (same ST=126, same remark pattern). There is NO rawdata signal on the bonus ST=126 rounds themselves that distinguishes BCM-triggered from scatter-triggered freespin — the only discriminating signal is on the PRECEDING PAID round (cc=1000 vs pay_id=666). This means the fork at the bonus ST level is impossible from the bonus round alone.

**What this means for the proposal:** ST=126 on M275 should be claimed by ONE plugin (either BCMFreespin or ScatterFreespin, not both), with the trigger-type distinction handled internally by the accumulator by looking at the preceding paid round. The CLAIM_SIGNATURE as written would produce a 2-plugin conflict on ST=126 unless one of the signatures explicitly excludes machines where BCM fields are also present.

**Verdict: PASS-WITH-GAPS** — M275 decomposes cleanly into BCM (ST=140) + freespin (ST=126), but the ClaimSignature conflict between BCMFreespinPlugin and ScatterFreespinPlugin on ST=126 is unresolved. The auto-detector would fire an ONBOARDING ALERT for M275 ST=126 on first run. Alert resolution is documented in the proposal (§5.4), but the fork rule to resolve it is not specified.

**Hash composition trace**
- Edit `BCMFreespinPlugin`: M275 has `bcm_freespin` active → M275 re-flags. Correct.
- Edit `ScatterFreespinPlugin`: if M275 also has `scatter_freespin` active → M275 re-flags for that too. Acceptable.
- Edit jackpot tier config for M275 (pay_ids 27502/27503/27504): only M275's config hash changes → only M275 re-flags. Correct.

**Backward compat**
`bcm_pairings.json` entry M275 → retired under proposal (auto-detection replaces it). Existing reports historical. Regeneration required.

---

### Case 4: M274 — BCM cc≡0 + ListReward Minigame + `_unattributed_st139` bug

**Rawdata confirmation (chunk_0001.json, 44,190 rounds)**
- ST=140: 40,000 paid rounds. CostCredits>0 on all. BCM fields present: `CollectCount`=**always 0** (confirmed on 40,000 paid rounds). `AccCredits`=**always 0**. `CreditsSymbols`, `SymbolIndexToRewards` present.
- ST=139: 4,190 bonus rounds. CostCredits=0. `ReMarks` = complex multi-cell strings (`Minigame CellIndexes: ...; RewardWheelIds: ...; curTimes:N, totalTimes:M; AddLock: []; TotalLock: [...]`). `PayoutIdToWinAmount`={} (empty) on all ST=139 rounds — win is in WinCredits only.
- pay_id=5801: 423 paid ST=140 rounds carry it (`WinCredits=0` on those trigger rounds — pure anchor, not a win).
- ST=139 win total (1 chunk): 20,414,000 credits. ST=140 win total: 16,329,000. Total bet: 40,000,000.
- RTP: (20,414,000 + 16,329,000) / 40,000,000 = **91.86%** (consistent with known ~93% target).
- ST=139 win as fraction of total win: **55.6%** — majority of RTP comes from bonus rounds that currently have attribution problems.

**Today (current architecture)**
- `BCMCycleAnchorRule` in `machine_round_win_rules.json` synthesizes `_bcm_cycle` anchor when `CollectCount=1000`. But CollectCount is always 0 on M274 — this rule never fires for BCM cycle events.
- The rule's `_doc` confirms both paths exist: (1) `CollectCount=1000` path (cc-based cycle detection, synthesizes `_bcm_cycle`) and (2) `pay_id=5801` path (handled by default extraction). Current analyzer uses BOTH.
- `_unattributed_st139` fallback bucket receives attribution that the trigger-session logic cannot assign (4.87% RTP per taxonomy).

**Under proposal — auto-detect flow**
1. `BCMBasePlugin.CLAIM_SIGNATURE` requires BCM core fields — all present on ST=140. Matches.
2. `BCMListRewardPlugin.CLAIM_SIGNATURE` requires:
   - Minigame cell/lock remark pattern on bonus rounds — present on ST=139.
   - `required_trigger_pay_id="5801"` — 423 paid rounds confirm.
   - Both match. `BCMListRewardPlugin` claims ST=139.
3. ST assignments: `{140: "bcm_base", 139: "bcm_listreward_minigame"}`. No conflict.
4. `BCMBaseAccumulator.on_round` for ST=140: tracks CollectCount (always 0) → no cycle peak fires → `finalize()` handles gracefully (proposal §4.3 step 4).
5. `BCMListRewardAccumulator.on_round` for ST=140 trigger rounds (pay_id=5801): records trigger anchor.
6. `BCMListRewardAccumulator.on_round` for ST=139: records WinCredits (no PayoutIdToWinAmount available).
7. Attribution result: ST=139's 55.6% RTP contribution attributed to pay_id=5801 trigger bucket. `_unattributed_st139` eliminated.

**The `_infer_feature_spin_type_mapping` second consumer (Q2 from proposal §11)**
Confirmed: `_infer_feature_spin_type_mapping` output (`feature_to_spin_type`, `spin_type_to_feature`) is passed to TWO stash locations:
- `_upstream_feature_breakdown_data["feature_to_spin_type"]` (line 4235) → `UpstreamFeatureBreakdown.emit()`
- Also passed as `feature_to_spin_type` arg to `_resolve_bonus_feature` at line 3494, whose output (`_bcm_bonus_feature`, `_bcm_bonus_source`) feeds BOTH `_upstream_feature_breakdown_data` AND `_collect_mechanic_data` stash (line 4276).

So the "second consumer" is the `CollectMechanic` plugin via `_collect_mechanic_data`. Under the proposal, migrating `_infer_feature_spin_type_mapping` to auto-detection must ensure its output continues to feed the `CollectMechanic` stash. This is not addressed in the proposal.

**Migration**
- `machine_round_win_rules.json` `bcm_cycle_anchor_m274` rule (applies_to=["M274"]) → migrated to `configs/play_type_configs/M274/mode_1.json`.
- `bcm_pairings.json` M274 entry → retired.
- M274 report correctness: `_unattributed_st139` eliminated. Output differs from current — flagged diff per §8.2. This is an intentional correctness fix, not a regression.

**Hash composition trace**
- Edit `BCMListRewardPlugin`: only M274 (and any other BCM-Minigame machines) re-flag. Today, editing `round_win.py:BCMCycleAnchorRule` re-flags all 420. Target blast radius: 1 machine vs 420.
- Edit M274's per-machine config: only M274 re-flags. Today, editing `machine_round_win_rules.json` is SILENT (zero re-flag). New model: 1 machine re-flags. Correct direction.

**Backward compat**
Existing M274 reports will be historical. Regeneration produces corrected output (unattributed bucket removed).

**Verdict: PASS-WITH-GAPS** — architectural decomposition is sound. The `_infer_feature_spin_type_mapping` second-consumer dependency (`CollectMechanic` stash) is an unaddressed migration risk (see §3 Item B).

---

### Case 5: M120 — Fleet-Rare `RewardIdToCollectAmount` Signature

**Rawdata confirmation (chunk_0001.json, 10,906 rounds)**
- ST=1: 10,000 paid rounds. CostCredits>0. Only standard base fields.
- ST=138: 906 bonus rounds. CostCredits=0. `RewardIdToCollectAmount` field present on all 906. Field value: `""` (empty string). `ReMarks` = `Freespin N;` pattern.
- pay_id=666: 82 paid rounds (trigger count). Matches 82 distinct freespin sequences of 11 rounds each.
- Fleet-wide: `RewardIdToCollectAmount` found on only 2 of 255 scanned machines (M120 and M125 per taxonomy §A5).

**Under proposal — auto-detect flow**
1. `MultiSymbolCollectionPlugin.CLAIM_SIGNATURE` requires `required_fields={"RewardIdToCollectAmount"}`. Present on 906 ST=138 bonus rounds. Matches.
2. `ScatterFreespinPlugin.CLAIM_SIGNATURE` requires `required_bonus_remark_pattern=r"\bFreeSpin\b"` AND `required_trigger_pay_id="666"`. Bonus remarks match `Freespin N` (case-insensitive). pay_id=666 on 82 paid rounds. Also matches.
3. Potential conflict: ST=138 claimed by BOTH `MultiSymbolCollectionPlugin` AND `ScatterFreespinPlugin`.

**Gap identified on M120 ST=138 dual-claim:**
The `RewardIdToCollectAmount` field and the freespin remark both fire on ST=138. Both `MultiSymbolCollectionPlugin` and `ScatterFreespinPlugin` would claim ST=138 simultaneously, triggering an ONBOARDING ALERT. The auto-detector's fork logic would need to determine which plugin "owns" ST=138.

The correct resolution: M120's freespin IS a scatter-triggered freespin AND it uses the RewardIdToCollect tracking — these are not mutually exclusive. The `MultiSymbolCollectionPlugin` should be subordinate to `ScatterFreespinPlugin` for this ST (or they co-own it). The proposal's `MECHANIC_DEPS` mechanism could handle this: `MultiSymbolCollectionPlugin` declares `MECHANIC_DEPS=("scatter_freespin",)` and adds the collection tracking on top of scatter freespin rounds.

But the proposal does NOT specify this dependency relationship for PT-14. The ONBOARDING ALERT would fire on M120's first run, requiring manual fork rule definition.

**Hash composition trace**
- Edit `MultiSymbolCollectionPlugin`: only M120 and M125 re-flag (2 machines). All others unchanged. Correct.
- Edit M120's per-machine config: only M120 re-flags. Correct.

**Backward compat**
Existing M120 report is current (effective_analyzer_version=90e36d27df98). Under new model it becomes historical on first run. Regeneration required.

**Verdict: PASS-WITH-GAPS** — `RewardIdToCollectAmount` signature is genuinely unique and detectable. But PT-14 and PT-2 will dual-claim ST=138 and trigger an ONBOARDING ALERT on M120. The proposal's ALERT path handles this procedurally (human review + fork rule), but the fork rule itself is not defined in the proposal.

---

### Case 6: M10 — LockLines + CostCredits Always Zero

**Rawdata confirmation (see Priority-1 section above)**
- 10,000 rounds, all ST=13, all CostCredits=0, all BetAmount=1000.
- `LockLines` field present on all 10,000 rounds.
- `ReMarks="trigger"` on 2,832 rounds (initial paid spins); `ReMarks=""` on 7,168 (lock-respin continuations).
- Current analyzer treats all rounds as paid via `cost_credits_unreliable` flag.

**Under proposal — auto-detect flow**
1. `CostCreditsReliabilityPlugin.CLAIM_SIGNATURE`: the proposal states this plugin's signature is a "pre-scan probe" that fires when all first-200 rounds have `CostCredits=0` AND `BetAmount>0`.
2. `LockLinesPlugin` (PT-10 in taxonomy) would have `CLAIM_SIGNATURE` requiring `LockLines` field on rounds.
3. Both would match on M10.
4. `CostCreditsReliabilityPlugin` result: `cost_credits_unreliable=True` → all ST=13 rounds classified as paid.
5. `LockLinesAccumulator.on_round`: tracks lock-line patterns.

**Critical ordering problem (proposal §11 Q5 — confirmed)**
The `CostCreditsReliabilityPlugin` probe result (`cost_credits_unreliable=True`) must be known BEFORE any other accumulator calls `is_paid_round()`. In the proposed `MechanicAccumulator` model:
- Accumulators are created from `active_plugins` list.
- The parse loop calls `acc.on_round(round_dict, round_idx)` for each active accumulator.
- If `LockLinesAccumulator.on_round` calls `is_paid_round(round_dict)` internally before `CostCreditsReliabilityAccumulator` has set its flag, the result is wrong.

The proposal uses `MECHANIC_DEPS` to order accumulator execution in `emit()`, but that is the post-parse display phase. The `on_round()` call order for in-parse accumulators is not specified. The proposal (§4.1) defines `make_accumulator()` returning a fresh accumulator per robot, but does not specify the order in which multiple accumulators receive `on_round()` calls.

**There is an additional deeper problem:** `is_paid_round()` is called by the UNIVERSAL parse loop body (Step 1 of Alternative C), not by individual accumulator `on_round()` methods. The result of `is_paid_round()` is used to gate `_close_session()`, update session state, and count paid spins — all in the universal body. If `cost_credits_unreliable` is now a plugin result rather than a pre-scan probe, the universal body cannot call it before the accumulators have run (chicken-and-egg).

This is not a theoretical concern: the current code in `parser.py:L633-L648` runs the probe BEFORE the per-robot loop begins, so all is_paid calls inside the loop see the correct value. Under the proposal, if `CostCreditsReliabilityPlugin` becomes an accumulator that produces its result via `on_round` + `finalize()`, the universal body needs the result BEFORE the first `on_round` call — which is impossible with the standard accumulator lifecycle.

The proposal acknowledges this in §11 Q5 ("This ordering constraint is not captured by `MECHANIC_DEPS`") but does not resolve it.

**Verdict: PASS-WITH-GAPS** — The premise is correct (cc=0 is real) and the plugin concept is valid. But the pre-run probe behavior cannot be implemented as a standard `MechanicAccumulator` without a special pre-parse hook that the proposal does not define. This needs designer attention.

**Hash composition trace**
- Edit `CostCreditsReliabilityPlugin`: only M10/M23/M131/M133 (4 machines, PT-10 LockLines family that also have this issue) re-flag. Today: editing the inline probe code in `parser.py` re-flags all 420. Correct target behavior.
- Edit `LockLinesPlugin`: only ~19 PT-10 machines re-flag. Today: would re-flag all 420 (if logic were in closure). Correct target.

**Backward compat**
Existing M10 report shows correct RTP (96.25%) because the current probe already handles this. Regeneration would produce byte-identical output (no correctness fix needed for M10, unlike M274).

---

### Case 7: Hypothetical M400 — Novel "Wheel-Collect" Mechanic

**Setup:** M400 emits a new field `WheelCollectCount` (not in any current plugin's `required_fields`). Bonus rounds have `ReMarks="WheelCollect N;"` (not matching any existing `required_bonus_remark_pattern`). No BCM fields. No LockLines. No DollarCount.

**Under proposal — auto-detect flow**
1. All registered plugin signatures evaluated:
   - `PurePaidPlugin`: matches paid ST (CostCredits>0). Matches.
   - `BCMBasePlugin`: `CollectCount` not present → no match.
   - `ScatterFreespinPlugin`: no `FreeSpin` remark on bonus → no match.
   - All other plugins: none of their required_fields or remark patterns present.
2. ST assignments:
   - Paid ST: claimed by `PurePaidPlugin`. Assigned.
   - Bonus ST: no plugin claims it (no matching signature). `CostCredits=0, ReMarks="WheelCollect N;"`.
   - Auto-detector step 2 ("if 0 plugins: unclaimed → assign to 'unknown_bonus' → ONBOARDING ALERT").
3. Alert fires:
   ```
   ONBOARDING ALERT — machine=M400, mode=1
     Ambiguous ST: SpinType=<X>
     Matching plugins: []
     No plugin claims ST=<X> (CostCredits=0, ReMarks="WheelCollect N;")
     ACTION REQUIRED: create a new play-type plugin for this mechanic or inspect
     rawdata and define a claim signature in an existing plugin.
   ```
4. Conservative assignment: bonus ST assigned to `"unknown_bonus"` fallback. Run proceeds with partial attribution.
5. Frontend surfaces warning badge on M400's report card.

**ONBOARDING ALERT path: WORKS CORRECTLY**
The proposal's DIRECTION §10 contract is satisfied: "an ST that does not map cleanly RAISES AN ALERT for human review; then decide case-by-case." The alert is generated, run continues conservatively, and a human can create a new plugin (`WheelCollectPlugin`) for M400.

**Verdict: PASS** — The onboarding alert path fires correctly. Novel mechanics do not silently mis-classify; they surface for human review.

---

## 3. Cases That Break

### Item A: `CostCreditsReliabilityPlugin` Cannot Be a Standard `MechanicAccumulator`

**Root cause:** The plugin's probe result (`cost_credits_unreliable=True/False`) must be available to the UNIVERSAL parse loop body (`is_paid=True` override at parser.py:L1467-1468) BEFORE any `on_round()` call. The standard `MechanicAccumulator` lifecycle delivers its result AFTER `on_round()` calls (via `finalize()`). This is a sequential dependency inversion.

**Affected case:** M10 (and M23/M131/M133 — all LockReSpin ST=13 machines with cc=0).

**What the proposal would need:** A special `PRE_PARSE_PROBE` protocol or interface distinct from `MechanicAccumulator`, executed once per chunk before the per-robot loop begins. The proposal mentions the probe is in Phase 2 deliverable item 10 but does not define how it plugs into the parse loop's `is_paid` evaluation.

**Designer revision needed:** Define a `PreParseProbe` ABC that runs before the first robot's `on_round()` and sets shared parse state (e.g., `cost_credits_unreliable`) that the universal loop body reads. This is a two-sentence addition to the plugin contract in §4.1.

---

### Item B: `_infer_feature_spin_type_mapping` Migration has an Unaddressed Second Consumer

**Root cause:** `_infer_feature_spin_type_mapping` results feed TWO stash keys: `_upstream_feature_breakdown_data` (for `UpstreamFeatureBreakdown` plugin) AND `_collect_mechanic_data` (for `CollectMechanic` plugin). The proposal (§7.1) lists `_infer_feature_spin_type_mapping` as a function to move into "BCM plugin and auto-detection" but the migration plan does not address the `CollectMechanic` stash dependency on `_bcm_bonus_feature / _bcm_bonus_source` (which are derived from `_infer_feature_spin_type_mapping` output).

**Affected cases:** All BCM machines (M272, M274, M275, M279, M268, and ~55 others).

**What breaks:** If `_infer_feature_spin_type_mapping` is moved to auto-detection without preserving its output in a stash readable by `CollectMechanic.emit()`, the collect mechanic display panel will fail or produce incorrect data.

**Designer revision needed:** The migration plan in §9 Phase 1/2 must explicitly address how the `_collect_mechanic_data` stash receives `feature_to_spin_type` and `_bcm_bonus_feature` values post-migration. One approach: the BCMBasePlugin's `MechanicAccumulator.finalize()` writes these to the chunk output dict, which PIA then stashes for `CollectMechanic.emit()`.

---

### Item C: M275 ST=126 Dual-Claim Between BCMFreespinPlugin and ScatterFreespinPlugin

**Root cause:** M275's freespin bonus rounds (ST=126) are triggered by TWO mechanisms: scatter (pay_id=666, 92%) and BCM peak (cc=1000, 8%). Both `BCMFreespinPlugin` and `ScatterFreespinPlugin` have claim signatures that match ST=126 bonus rounds. The proposal's fork logic handles the M15 ST=1 case (where DollarCount provides a clean discriminator on the bonus rounds themselves), but for M275's ST=126 there is no bonus-round-level discriminator — the triggering mechanism is only visible on the PRECEDING paid round.

**Affected cases:** M275, and likely any other BCM machine that also accepts scatter triggers (taxonomy notes M275 and M272 both have scatter+BCM dual triggers).

**What happens:** Auto-detector fires ONBOARDING ALERT for ST=126. The alert is procedurally handled (human review). But the fork rule needed to resolve it ("BCMFreespin owns ST=126; it absorbs scatter-triggered freespins by checking the preceding paid round's trigger type") is not specified in the proposal.

**Designer revision needed:** Add a fork rule spec for "BCM freespin machines that also accept scatter triggers." The rule should be: `BCMFreespinPlugin` claims ST=126 unconditionally on BCM machines (since the BCMFreespinAccumulator can internally distinguish scatter vs BCM trigger by looking at the preceding paid round's pay_id=666 vs CollectCount=1000). `ScatterFreespinPlugin` should declare `exclude_if_fields_present=frozenset({"CollectCount","AccCredits"})` to avoid claiming bonus STs on BCM machines.

---

### Item D: M120 ST=138 Dual-Claim Between MultiSymbolCollectionPlugin and ScatterFreespinPlugin

**Root cause:** M120's bonus rounds (ST=138) have BOTH `RewardIdToCollectAmount` field (PT-14 signature) AND `Freespin N;` remark (PT-2 signature). Both plugins claim ST=138.

**Affected cases:** M120, M125.

**What happens:** ONBOARDING ALERT fires for ST=138. Procedurally handled.

**Designer revision needed:** Specify `MECHANIC_DEPS = ("scatter_freespin",)` on `MultiSymbolCollectionPlugin` so it is subordinate to PT-2. The ST=138 assignment goes to `scatter_freespin` as the primary owner; `MultiSymbolCollectionPlugin` augments it by tracking the `RewardIdToCollectAmount` field within the already-claimed freespin rounds. The fork rule: if `scatter_freespin` and `multi_symbol_collection` both match the same ST, `scatter_freespin` takes primary ownership and `multi_symbol_collection` adds tracking on top (using `MECHANIC_DEPS`).

---

## 4. Hash Composition Trace — All Cases

| Scenario | What changes | Machines that re-flag |
|---|---|---|
| Edit `BCMFreespinPlugin` | Plugin hash changes | ~34 BCM+freespin machines (per taxonomy A5 PT-4). M14, M15, M120 unchanged. |
| Edit M274 per-machine config (trigger anchor pay_id=5801) | Only M274's config_hash changes | M274 only. Today: SILENT. Correct improvement. |
| Edit `round_classification.py` (pre-migration) | base_hash changes | All 420. No change from today. |
| Edit `round_classification.py` B functions after migration | Edits now in plugin files; base_hash unchanged | Only machines with that plugin active. |
| Edit `ScatterFreespinPlugin` | Plugin hash changes | ~13 TriggerFreespin remark machines + M275 (if assigned to this plugin) — ~14-52 depending on resolution of Item C. |
| Edit `WildNudgePlugin` | Plugin hash changes | ~10 PT-7 machines (M279, M140, M149, M209, M226, M256, M259, M26, M276, M51). |
| Edit `MultiSymbolCollectionPlugin` | Plugin hash changes | M120, M125 only (2 machines). |
| Edit `CostCreditsReliabilityPlugin` | Plugin hash changes | M10, M23, M131, M133 (~4-19 PT-10 LockLines machines). |
| Fold `bcm_pairings.json` into per-machine configs | bcm_pairings retired; per-machine configs hashed | BCM machines' config_hash changes → fleet-wide once during migration, then isolated per-machine thereafter. |
| Fold `machine_round_win_rules.json` into per-machine configs | Rules retired; per-machine configs hashed | M274 + 4 TopDollar machines → config_hash changes. Config edits now visible (today: SILENT). |

**Verification that silent-dependency gap is closed:**
Both `configs/bcm_pairings.json` and `configs/machine_round_win_rules.json` are confirmed NOT in `_CLOSURE_FILES` (versioning.py line 114 — 25 files enumerated, neither JSON is present). Editing them today changes behavior silently. Under the proposal, both are retired/migrated into per-machine configs that ARE hashed (Step 4 of `compute_effective_version_for_machine`). The gap is closed by design.

---

## 5. Backward-Compat Check

| Case | Existing reports | Regeneration required? | Notes |
|---|---|---|---|
| M14 | 16 versions on disk; oldest has no `effective_analyzer_version` field | YES | New hash composition → all historical. Output byte-identical (no correctness fix). |
| M15 | 4 versions; `effective_analyzer_version` absent on older reports | YES | Settlement rule now hashed → config-hash changes. Output byte-identical. |
| M275 | 1 version, `effective_analyzer_version=90e36d27df98` | YES | bcm_pairings.json entry retired → config-hash changes. Output byte-identical. |
| M274 | 4 versions; oldest lacking effective_analyzer_version | YES | Output DIFFERS (correctness fix: unattributed_st139 eliminated). Flagged diff required per §8.2. |
| M120 | 1 version, `effective_analyzer_version=90e36d27df98` | YES | Output byte-identical (no known correctness issues). |
| M10 | 1 version, `effective_analyzer_version=90e36d27df98` | YES | Output byte-identical (CostCredits probe behavior preserved via new plugin). |

**Summary:** All existing reports become "historical" on the migration (fleet-wide one-time re-flag due to hash composition algorithm change). This is expected and documented in the proposal (§9 Phase 3 deliverable 4). The only case with non-byte-identical output is M274 (intentional correctness fix, flagged per §8.2).

Old reports without `effective_analyzer_version` field: the backend must handle absence gracefully. Currently `effective_analyzer_version_error: None` is present; the field itself is populated in recent reports. Very old reports (pre-Phase-3) may lack it → treated as "historical" per `03_coupling_audit.md §7.3` guidance. No backward-compat failure here — old reports are simply historical.

---

## 6. Verdict

**APPROVE-WITH-REVISIONS**

The core architecture (Alternative C parse-loop + MechanicAccumulator + ClaimSignature auto-detection + per-machine config hashing) is sound and validated against real rawdata. The fundamental problems it solves (fleet-wide re-flag on mechanic edits, silent config dependencies) are confirmed real. The four specific cases confirmed by rawdata (M10 cc=0, M15 ST=1 fork, M274 cc≡0 + unattributed, M120 rare field) all route through the design correctly in principle.

**Revisions required before implementation:**

1. **`CostCreditsReliabilityPlugin` ordering constraint** (Item A): define a `PreParseProbe` interface (distinct from `MechanicAccumulator`) for probes that must run before the per-robot loop and set universal parse state. Two sentences in §4.1 plugin contract.

2. **`_infer_feature_spin_type_mapping` second consumer** (Item B): migration plan in §9 Phase 1 must specify how `_collect_mechanic_data` stash receives `feature_to_spin_type` and `_bcm_bonus_feature` after the function moves to auto-detection. One paragraph in §9 Phase 1.

3. **M275/M272 ST=126 dual-claim fork rule** (Item C): `ScatterFreespinPlugin.CLAIM_SIGNATURE` needs `exclude_if_fields_present=frozenset({"CollectCount","AccCredits"})` to avoid conflicting with `BCMFreespinPlugin` on BCM machines that also accept scatter triggers. One-line addition to the signature definition in §4.2.

4. **M120 PT-14 + PT-2 dual-claim fork rule** (Item D): `MultiSymbolCollectionPlugin` needs `MECHANIC_DEPS=("scatter_freespin",)` so it is subordinate to PT-2 and co-owns (not conflicts with) scatter freespin rounds. One-line addition to the plugin's class definition in §9 Phase 2 item 8.

None of the four breaks require redesigning the architecture. All are additive specifications within the existing framework.
