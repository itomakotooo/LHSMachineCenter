# M275 / mode 1 — Wave 2 REUSE ADJUDICATION (the gate)

Independent conclusion derived FIRST from Wave-1 understanding (`01_understanding.md`,
89,090 rounds, 2 real chunks `_cache_version:3`, single md5 bucket 8c89bc95…/9b453ffc…),
THEN compared to the FROZEN framework (`machine_spec.py` canonical sets, `features/*.py`
plugin code, `core/parser.py`, `play_types/{bcm_cycle,wild_nudge}.py`,
`fresh_slotlab/{trigger_sessions,round_win}.py`,
`configs/{machine_round_win_rules,bcm_pairings}.json`). Layer-3 audit ran the CURRENT
`report_engine.generate_report_from_chunks` on M275's **2 real cached chunks**
(89,090 rounds — matches W1 exactly; RTP 89.23625 == W1 89.24).

**Audit harness (THROWAWAY — not the deliverable):** `_tmp/m275_reuse_audit/` —
`run_audit.py` (current engine on real chunks via a draft schema-valid manifest in
`_tmp/m275_reuse_audit/manifests/`), `audit_out.txt` (full semantic dump), plus an
independent raw-rounds session recompute (inline, transcribed below). The real
`configs/` were **NOT** modified.

---

## ⚠ TOP-LINE: ONE ABORT — the session-centric KPI machinery does NOT assemble M275

| ST / machinery | reel/payid/outcome DIMS | the MECHANIC dim | verdict |
|---|---|---|---|
| **st140 NormalCollectionSpin** (paid reel spin + collect counter) | **STRICT-REUSE** (4 PER_SPINTYPE) | **STRICT-REUSE** `collect_mechanic` + bcm_cycle primitives | **STRICT-REUSE** |
| **st126 NewFreespin** (free reel spin, ExtraRatio ladder) | **STRICT-REUSE** (4 PER_SPINTYPE) | **NEW-EVENT** (no signature match; `respin_dynamics` fits via role, RUN-verified; ER/skin/FS-arc parser-blind) | **NEW-EVENT** (mechanic) |
| **pid attribution / round_win / rtp_integrity** | n/a | self-settling; NO rule needed; parity EXACT | **STRICT-REUSE** |
| **session-centric KPI layer** (`_close_session` fold) | n/a | **drops 45.8% of all win from the session view on M275** | **ABORT — escalate to framework team** |

### THE ABORT (blocks onboarding completion)

**Finding:** the shared session-centric machinery (parser closure `_close_session` +
`sess_state.is_trigger_session` + `trigger_sessions.round_has_credited_win`) silently
EXCLUDES every scatter-opened freespin session's win from the session/paid-round (付费回合)
KPI dimension on M275. Mechanism, traced in code:

1. `compute_trigger_sessions` anchors a session on any paid round carrying a win==0 pid —
   M275's scatter trigger pid **666** (829 rounds) qualifies.
2. Anchored sessions take the helper path: `session_win` counts ONLY bonus rounds NOT
   already credited at pid level (`round_has_credited_win`, raw check (a):
   non-empty `PayoutIdToWinAmount` with a nonzero value). M275's st126 rounds ALL
   self-credit (W1: `sum(payids)==WinCredits` 89,090/89,090) → **helper session_win = 0**.
   That is CORRECT for pid attribution (no double count — parity holds, below) ...
3. ... but `_close_session` uses the SAME number for the SESSION dimension:
   `s_win = paid_round_win + bonus_win_from_helper(=0)`, and the
   `is_trigger_session` flag suppresses the naive `sess_state["win"] += win_amt`
   accumulation. The scatter sessions' 32,637,000 + the double-trigger block's 80,500
   (45.83% of ALL win) simply vanish from session buckets / volatility /
   hit_and_payout. The cc-peak (BCM) sessions survive only because they have NO
   win==0 anchor pid → naive path.

**Held trace (REAL data, independently recomputed from raw rounds; "TRUE" additionally
reconciles EXACTLY with the server's OWN session-centric `TotalWin` taxonomy, W1 §5.1
— ≥10x tiers 676+533+226+81+1 = 1,517):**

| session-centric metric (per paid round, n=80,000) | TRUE (raw + server TotalWin) | REPORT (live run) | error |
|---|---|---|---|
| `volatility.avg_return_x` | 0.89236 | **0.48339** | −45.8% (== (71,389,000−32,637,000−80,500)/80,000,000 — exact) |
| sessions with win (`win_hit_rate`×80k) | 11,893 | **11,150** | −743 (= the 743 win-only-via-scatter-freespin sessions) |
| ≥10× sessions (`big_win_x10_rate`×80k) | 1,517 | **851** | −44% (851 = 788 st140-own + 63 naive-BCM — exact) |
| `max_observed_return_x` | 338.0 (best scatter session) | **172.5** | = the best NAIVE-path (BCM) session only |

Four independent bullseyes; the mechanism is proven, not inferred.

**Why ABORT and not NEW/config:** there is NO config-only remedy. `round_has_credited_win`'s
raw check (a) is not rule-overridable, and even if a rule forced the helper to count the
bonus rounds, the same win would then ALSO be attributed to pid 666 → pid parity breaks
(double count). The correct fix — fold credited bonus wins into the SESSION dimension
while leaving the PID dimension untouched — is a **parser-closure change** (base_hash
flip; re-flags the fleet). Per the brief and the charter: shared-code modification
required → ABORT + escalate; do NOT patch in onboarding.

**Blast radius (framework team):** fleet-wide and PRE-EXISTING on the whole
"zero-win-anchor-pid + self-crediting bonus rounds" family (M273 + its ~84 variants,
M201, M209, M257 — the `trigger_sessions` Type-2 machines). M275 is merely the FIRST
machine to hit this path under the onboarding gate (M15 = Type 1 phantom offers → helper
correct; M43/M279 bonus blocks have no win==0 anchor → naive path correct). Undocumented:
`docs/REPORT_SPEC.md` locks only the pid-parity contract; no doc declares the session-view
drop. The user's default metric unit is exactly this dimension
(feedback_paid_round_default / feedback_session_semantics) — a M275 report served today
would understate the headline big-win KPIs by ~44% and halve the max session.

Everything ELSE audited below is held (STRICT-REUSE / NEW-EVENT with proof). After the
framework fix, re-running `_tmp/m275_reuse_audit/run_audit.py` and checking
`volatility.avg_return_x ≈ 0.8924`, `big_win_x10_rate×80k == 1,517`, `max == 338` is a
sufficient re-audit of this finding.

---

## Field signatures (identify "same ST" by SIGNATURE, not number)

Signatures from W1 §1 — every field at presence 1.0 (no optional fields on this machine).

| ST | M275 signature | matches an existing validated ST? |
|----|----------------|-----------------------------------|
| **st140** | full paid-reel set (`StopSymbolsByCol`/`PayoutByPayline`/`PayoutIdToWinAmount`/`RewardLastNode`/`ReelSkin`/`BetAmount`/`CostCredits=1000`/`WinCredits`) **+ the 4 collect fields** `CollectCount` (1→1000 metronome, +1/paid spin) /`AccCredits` (=100×CC)/`CreditsSymbols`/`SymbolIndexToRewards` | **YES — M279 st140 (validated, user-signed-off)**, field-for-field: every field in M279's manifest signature is present ≥99% here with the same shape (deterministic 1000-peak CollectCount metronome, AccCredits = 100×CC). M275's only supersets are constants (`SymbolIndexToRewards`="{}" always, `GameplayTriggerType`=0 always on st140) — constants do not change the shape. Same ST → **MUST strict-reuse**. |
| **st126** | the free-reel-spin set (st140's reel/payid set, `CostCredits=0`, `ReMarks`="Freespin N; ", own skins 11/21/31) **+ `ExtraRatio`** (escalating ×100 multiplier, 100% presence, load-bearing: win law = base×(ER/100)×wildNx, W1 §7.3) **+ `GameplayTriggerType` ∈ {0,2}** (perfect trigger-path discriminator) | **NO exact match.** M43 st50 / M279 st36 (`respin` role) match the free-reel SUB-signature but carry NO `ExtraRatio`; M15 st14 carries `ExtraRatio` but is an offer/choice shape (DollarCount/ChosenDollar/OfferValue, no reels). A reel-spin signature WITH a 100%-presence escalating-multiplier field is a genuinely **NEW event**. |

ST numbers: M275 st140 COLLIDES with M279 st140 by number AND by signature — the rare
"same number, same signature" case; reuse is driven by the signature match, the number is
incidental. st126 collides with nothing (M272's st126 is referenced in framework
docstrings as the same family but M272 is not a validated manifest machine).

---

# PER-ST 3-LAYER AUDIT + VERDICT

## st140 NormalCollectionSpin — STRICT-REUSE (PER_SPINTYPE **and** collect_mechanic)

**Layer (a) signature:** matches M279's validated st140 exactly (table above) — the
collect-counter paid-reel shape, the very archetype `collect_mechanic` was built for
(plugin docstrings: "Phase C5 of analyzer unbundle (M275-driven)") and M279 re-validated.

**Layer (b) code:** the 4 PER_SPINTYPE plugins (`payouts_by_spin_type`,
`reel_marginal_by_spin_type`, `spin_type_outcomes`, `spin_type_rtp_buckets`) are ST-int
keyed, field-presence driven, no machine/ST literals (re-verified by literal scan: all
M275/140/126/666 occurrences are docstring examples). The collect machinery is structural:
`bcm_cycle.detect_cycle_peak` / `compute_robot_cycle_peaks` skip `CollectCount=None`
bonus rounds so the cc=1000→1 reset is seen ACROSS the st126 block (the M279 Bug-4 fix
applies verbatim to M275's NewFreespin block); `collect_mechanic.emit()` builds from
those accumulators, no literals.

**Layer (c) run on M275 real data (current engine, 2 chunks):** every number reconciles
with W1 to the unit:
- `spin_type_breakdown` st140: spins=80,000, hit_rate=0.1385875 (== W1 13.86%),
  total_win=35,857,500 (== W1 exact), behavior `paid`, feature_name
  `NormalCollectionSpin` (mapping inferred correctly).
- `payouts_by_spin_type["ST140_paid"]`: all 12 pids EXACT vs W1 §8.1 (1:1025, 2:1225,
  3:457, 4:3464, 5:579, 6:737, 7:1834, 8:3513, 27502:17, 27503:14, 27504:122,
  **666:829×win 0**); pid 666 notes `is_trigger_marker:true`, symbol_combo
  `bonus|bonus|bonus` ×829 (== W1 §8.2's 3-bonus-reels proof).
- `collect_mechanic` (top-level): `detected_cycle_length=1000` (the metronome, W1 §6),
  `bonus_feature="NewFreespin"` source=**config** (`bcm_pairings.json` M275 mode 1 —
  W1-correct), `estimated_correction_pp=0.0` — the ONLY RTP-bearing output, CORRECT
  (clean sample: every robot ends at cc=1000 = 5 exact cycles, `robots_with_pending_cycle=0`).
  Cosmetics identical to the blessed M275 golden (`cache/_playtype_golden_pristine/M275`):
  `completed_cycles_total=64` (resets only; true cycles 80), always-on `clamp_warning`
  (pending_share 0.8) — the KNOWN fleet-wide precision items from M279's manifest caveats.
  One M275-specific sharpening for the framework note: `avg_bonus_payout=555,180`
  divides the WHOLE NewFreespin win (92% of which is scatter-path) by cycle count —
  ~15× the true per-BCM-cycle payout (2,894,500/80 = 36,181). Harmless while the
  correction is 0.0; would over-correct on a truncated sample. Escalation list, not a blocker.

→ **STRICT-REUSE all four PER_SPINTYPE plugins + `collect_mechanic` verbatim.** Declare
`role: paid_spin, play: NormalCollectionSpin`. No new code for st140.

## st126 NewFreespin — dims STRICT-REUSE; mechanic NEW-EVENT. NOT a fork; NOT an abort.

### (i) reel/payid/outcome dims → STRICT-REUSE the 4 PER_SPINTYPE plugins

**Layer (a):** free-reel sub-signature (reels + payids + cost present) satisfies the
PER_SPINTYPE field contract. **Layer (b):** same generic ST-keyed plugins. **Layer (c):**
- `spin_type_breakdown` st126: spins=9,090, hit_rate=0.2503850 (== W1 25.04%),
  total_win=35,531,500 (== W1 exact), behavior `free`, `rtp_pct: null` (free ST — correct),
  rtp_contribution_pp=39.88, feature_name `NewFreespin`.
- `payouts_by_spin_type["ST126_free"]`: all 11 pids EXACT vs W1 §8.1 (1:282, 2:245,
  3:153, 4:837, 5:146, 6:193, 7:339, 8:710, 27502:6, 27503:8, 27504:32).
- Multiplier tail real and ER-amplified: per-ST bands reach ge200_lt500 (2 rounds —
  W1's 325× max round lives there); `spin_type_outcomes["ST126_free"]` win_bands +
  top_combos populated (`max_mult` is the pid-level fixed-prize max 100×, per that
  plugin's documented semantics; the per-round tail is in the band histograms).
- `spin_type_rtp_buckets` emits ONLY `ST140_paid` — **documented by-design** ("pure
  free-spin STs are silently omitted", paid-bet denominator); not a defect. The st126
  multiplier view is delivered via the per-ST bucket accumulators (respin_dynamics /
  spin_type_outcomes / upstream_feature_breakdown).

→ **STRICT-REUSE** for st126's reel/payid/outcome rows.

### (ii) the FREESPIN mechanic → NEW-EVENT

**No existing validated ST signature matches** (layer a, table above) → a genuinely NEW
event. What W2 verified about the EXISTING mechanic plugins on real data:

- **`respin_dynamics` (`respin` role) FITS and is RUN-CORRECT** if W3 declares
  `role: respin` (the closest KNOWN_ROLE: free cost=0 reel spin extending a paid spin,
  shares the trigger's SpinTimes 909/909 — W1 §3): `openers=908` (== W1's 908 distinct
  st140→st126 blocks; the double-trigger pair is one contiguous block — same merge the
  server's own SummaryWin does), `one_per_n_paid_spins=88.1`, `uplift_ratio=1.807`
  (== 25.04/13.86), `continuation_prob=0.9017` (= 8182/9074 — the 10-spin fixed session),
  `share_of_all_win=0.4977` (== W1 44.41/89.24), `fat_tail_ge20x_win_share=0.637`,
  burst-length histogram honestly flagged `parser_blind`. Reusing it via the role is
  allowed and verbatim. Whether `respin` is the right role for a fixed-10 freespin
  session is W3's design call (roles are an open set; `machine_spec.py` is base-excluded).
- **`bonus_chain_dynamics` (CROSS_CUTTING, always runs)** assembles the chain STRUCTURE
  correctly (`chain_count=908`, `avg_chain_length=10.0` exactly, retrigger 0 — W1: no
  retrigger structurally possible) **BUT its ExtraRatio surfaces are DEFAULT-FILLED, not
  data**: `extra_ratio_histogram=[{ratio:100, rounds:9090}]`, max-ratio quantiles all 100,
  depth curve flat 100 — while W1 §7.3 PROVES ER escalates 100→2800 on every session.
  Root cause (layer b): `parser.parse_freespin_remarks` reads ER from a ReMarks regex
  (M272-style "ExtraRatio" annotations); M275 carries ER in the round FIELD `ExtraRatio`,
  which the chain accumulator never reads. The blessed M275 golden shows the IDENTICAL
  flat-100 output — pre-existing, framework-blessed-as-bytes, but **semantically the
  "emits rows ≠ mechanic handled" trap**: W3/W4 must NOT cite this panel as ER coverage.
- **The ER ladder / FS-index arc / skin schedule are PARSER-BLIND** in the frozen
  framework: plugins receive per-chunk ACCUMULATORS, and no accumulator carries per-round
  `ExtraRatio`, FS-index×outcome, or per-round `ReelSkin`. Same boundary as M279's wheel
  cell-map / skin-11 breakout and M43's burst histograms — the framework team's queued
  "per-ST extraction layer" item. A NEW st126 plugin (W3/W4) may deliver every
  accumulator-derivable metric and MUST flag these sub-metrics `parser_blind`
  (M279 `wheel_dynamics` precedent), never fabricate them.

**Verdict NEW-EVENT** = declare st126 (`play: NewFreespin` — the literal FeatureWin key)
+ reuse `respin_dynamics` via role if W3 so designs + a NEW freespin-mechanic plugin for
what the accumulators expose, parser-blind flags for the rest. None of this modifies a
shared plugin → not a fork.

## Trigger / attribution / economy machinery — pid dimension STRICT-REUSE (no rule needed); session dimension = the ABORT above

**Round-win path (brief item 4):** every round self-settles (W1: sum(payids)==WinCredits
89,090/89,090) → **NO round_win rule needed, not even a SynthesizePayIdRule** (M275 absent
from `machine_round_win_rules.json` — correctly so; unlike M43 st51 / M279 st2 there is no
orphan win). PROVEN on the run: zero `_unattributed_*` buckets.

**rtp_integrity (brief item 5):** `passed=true`, L1 invariant OK, L2 no fallback buckets,
L3 anchors OK, L4 skip (engine passes no rawdata dir — not M275-specific).
`feature_errors: null`. **Parity EXACT:** sum(payout_ids_top20.rtp_contribution_pp) =
89.23625 == summary.rtp.point_pct == W1's 89.24. pid 666 carries win 0 (marker, not
money) with `notes.is_trigger_marker=true` — the st126 wins flow through their own pids
(the M273-pattern attribution the framework documents), no double count.

**Scatter-vs-BCM session attribution (brief item 3):** the existing machinery DOES
assemble the split, in `upstream_feature_breakdown`:
`NewFreespin [via NewFreespin]` win 32,637,000 / 8,280 rounds vs
`NewFreespin [via BCM cycle]` win 2,894,500 / 810 rounds + `BuffCollectionMap` 80×win 0.
vs W1 §7.1 ground truth (829 scatter / 80 cc-peak by the GTT discriminator): exact except
the ONE double-trigger round's GTT=0 half (10 rounds, 48,500) binned to the BCM bucket —
a 1-in-909 edge case (the server's own SummaryWin merges the same pair). Near-exact: PASS.
`detect_cycle_peak`=1000 verified live (cc=None st126 rounds skipped — the M279 fix).
Two LESSER label drifts for the framework list (display-level, not attribution):
1. `bonus_chain_dynamics.by_feature` uses the prev-round-pids heuristic
   (any pid → "NormalCollectionSpin"/random, empty → "NewFreespin"/forced): reports
   841/67 vs GTT truth 829/80 — the ~12-14 cc-peak trigger rounds that happened to carry
   ordinary line wins are mislabeled into the scatter family. M275's rawdata carries the
   PERFECT discriminator (GTT 0/2) but it never reaches the accumulators (parser-blind).
2. The same legacy convention repurposes server feature NAMES as path labels, so
   `payout_ids_top20` pid-666 `notes.trigger_target="NormalCollectionSpin"` — reads wrong
   (the scatter opens NewFreespin sessions); the ufb `[via …]` labels are the correct view.

**Session-centric KPI fold:** **ABORT — see top.**

---

## Cross-cutting framework notes (NOT reuse verdicts; coordinator/W3 must heed)

1. **[ABORT — blocking]** Session-centric KPI fold drops self-credited trigger-session
   bonus wins (top section; parser-closure fix; M273-family fleet-wide; held trace above).
2. **`bonus_chain_dynamics` ER surfaces default-filled on field-borne-ER machines**
   (flat-100 histogram/quantiles/depth-curve/`chain_ratio_sequences`; ReMarks-regex source;
   golden-identical so pre-existing) — misleading-constant output, per
   feedback_invariant_with_fallback_hides_drift a default masquerading as data. Framework
   item (read the `ExtraRatio` field / per-ST extraction layer).
3. **`machine_mechanics.free_spin.applicable=false` on M275** —
   `derive_mechanism_flags` keys on play=="freespin" EXACT (set membership); M275's play
   MUST be the literal FeatureWin key "NewFreespin" → flag False → the plugin's own
   M275-intent BCD fallback (its comment names M275!) is dead code; the report would
   self-contradict (bonus_chain_dynamics: 908 chains vs free_spin: not applicable).
   Shared-code fix (machine_spec/machine_mechanics); display-level; non-blocking.
4. **Chain trigger-path labeling** (prev-pids heuristic + name collision, above) —
   display-level precision item; the exact split needs GTT/cc in the accumulators.
5. **`collect_mechanic` cosmetics** — known fleet-wide family (M279 manifest caveats);
   M275 adds the scatter-polluted `avg_bonus_payout` (~15× true per-cycle) sharpening.
6. **md5 provenance (coordinator):** the engine stamps the ROSTER's current md5
   (2c98ce05…/ebad1145…) while these chunks are the HISTORICAL bucket 8c89bc95…/9b453ffc…
   (W1 §0). Any SERVED report for this bucket must go through the md5-scoped console
   generate path (`fd6b507`/`597e8bf`), stamped with the chunk md5s. Audit-run-only note.
7. **`spin_type_rtp_buckets` omits free STs by design** — W3: take st126's multiplier
   view from the per-ST bucket accumulators (respin_dynamics bands / spin_type_outcomes),
   don't expect an ST126 entry there.

---

## Summary of what onboarding may build (AFTER the ABORT is resolved; none is a fork)

- **st140:** nothing new — STRICT-REUSE the 4 PER_SPINTYPE + `collect_mechanic`.
  Declare `role: paid_spin, play: NormalCollectionSpin`. `rtp_integrity.paid_st: [140]`.
- **st126:** STRICT-REUSE PER_SPINTYPE dims; reuse `respin_dynamics` via role (W3 call);
  ONE NEW mechanic plugin for the freespin (accumulator-derivable metrics + `parser_blind`
  flags for ER-ladder/FS-arc/skin-schedule) + its frontend ST dimension (deliverable #5)
  + render gate 7. Declare `play: NewFreespin`.
- **Attribution:** NO round_win rule, NO SynthesizePayIdRule (self-settling, proven).
  `trigger: {payout_id: "666", opens: "NewFreespin"}`; bcm_pairings already correct.
- **BLOCKED until the framework team fixes the session fold** (or the user/coordinator
  explicitly accepts a degraded session view — not W2's call): re-audit = re-run
  `_tmp/m275_reuse_audit/run_audit.py`, expect `avg_return_x≈0.8924`,
  `big_win_x10_rate×80k=1,517`, `max_observed_return_x=338`.

*Evidence: current `report_engine.generate_report_from_chunks` on `rawdata/M275/mode_1`
(2 chunks, 89,090 rounds; RTP 89.23625 == W1; parity sum(pid pp)=89.23625 exact;
rtp_integrity passed; all per-ST pid tables == W1 §8.1 to the unit). Session-fold
counterexample independently recomputed from raw rounds AND reconciled against the
server's own TotalWin tier taxonomy (1,517 ≥10× sessions). collect_mechanic semantics
cross-checked against the blessed golden `cache/_playtype_golden_pristine/M275`
(byte-pattern identical, incl. the flat-100 ER histogram). Throwaway harness:
`_tmp/m275_reuse_audit/`. Real `configs/` untouched.*
