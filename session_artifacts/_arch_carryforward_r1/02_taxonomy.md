# 02 — Fleet Taxonomy (Carry-forward Round 1)

> **Date**: 2026-05-28
> **Role**: arch-taxonomist (Wave 1)
> **Input**: `session_artifacts/_arch_carryforward_r1/00_brief.md`,
>   `session_artifacts/_arch_analyzer_unbundle/02_taxonomy.md` (R0 baseline),
>   `docs/ARCH_TEAM_PROCESS.md` §1-§5,
>   rawdata spot-checks (M5, M27, M107, M113, M260, M275, M272),
>   source: `fresh_slotlab/analyzer/features/payouts_by_spin_type.py`,
>   `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`,
>   `fresh_slotlab/analyzer/features/collect_mechanic.py`,
>   `fresh_slotlab/player_impact_analyzer.py` lines 4810-4868,
>   `fresh_slotlab/analyzer/core/parser.py` lines 285-330,
>   `src/web_console/frontend/app.js` lines 6185-6200,
>   `tests/backend/test_full_pipeline_m272.py` lines 381-398
> **Output**: `session_artifacts/_arch_carryforward_r1/02_taxonomy.md`
> **Next consumer**: `arch-designer` (Wave 2)

---

## §1 Scope & Inventory

### Scope narrowing

This taxonomy is a **delta document** on top of the R0 baseline at
`session_artifacts/_arch_analyzer_unbundle/02_taxonomy.md`. The R0 document
fully classified all 256 base machines across 6 axes. The three Cluster D
carry-forwards (d1, d2/d3, d4) affect specific machine subsets; Clusters A
and E are fleet-agnostic infrastructure changes (no per-machine taxonomy
needed). This document focuses on those three subsets.

### Fleet reference

- **Base machines**: 256 (R0 baseline)
- **Variant machines**: 166 (share archetype with their base; not re-surveyed)
- **Total fleet entities**: 422

### Sampling strategy

Full enumeration was used for structural axes (payline counts, scatter marker
presence) because all data derives from the R0 taxonomy already computed from
observed rawdata. Spot-checks of 5 machines from each affected group were run
directly against cached rawdata chunks to confirm measurable criteria.

Machines spot-checked for d1 (paylines sort): M5, M27, M107, M113, M260.
PayoutByPayline confirmed as string format `line_id:win-pid(positions); ...`;
parsed by `parser.py` into `payout_id_payline_hits[pid_str][payline_id_str]`
where keys are **strings** (e.g. `"1"`, `"10"`, `"-1"`).

---

## §2 Clustering Axes (Carry-forward Delta)

Three axes are relevant for the Cluster D fixes. The R0 axes (Ax1-Ax6)
are referenced by name but not reproduced in full.

| Axis | Source | What it measures | Relevant fix |
|---|---|---|---|
| **Ax4: Payline count** | R0 taxonomy (rawdata `PayoutByPayline` max positive line_id) | Machines with 10+ paylines where string-sort diverges from int-sort | d1 |
| **Ax6: Scatter trigger marker** | R0 taxonomy (zero-win PIDs in line_id=-1) | Machines that use scatter marker PIDs | d2, d3 |
| **Ax7: Bonus feature count** | `bonus_chain_dynamics.by_feature` keys with non-zero `chain_count` | Number of distinct bonus features in `all_chains_by_feature` (determines d3 unique confidence) | d3 |

---

## §3 Per-Axis Clusters

### Ax4 Delta: Payline count — machines affected by d1 (sort bug)

The bug (`payouts_by_spin_type.py` lines 424-435):

```python
key=lambda x: x["payline_id"],   # sorts str keys: "10" < "2" (WRONG)
```

The sort key operates on `payline_id` which is a **string** (dict key from
`pid_payline_hits`, which in turn comes from `payout_id_payline_hits[pid][payline_id_str]`
where `payline_id_str = str(_c3lid)` per `parser.py` line 1869). String sort
produces `"1","10","11","2"` instead of `"1","2","10","11"`.

**Measurable criterion for bug impact**: any machine where the observed set of
positive payline IDs contains at least one value >= 10 (i.e., the string
representation of a two-digit ID sorts before a smaller one-digit ID).

**Special case**: line_id=-1 (scatter trigger line). String sort places `"-1"`
before `"1"` (since `"-"` < `"0"` in ASCII), which accidentally produces the
correct integer order for the single negative entry. However, when combined
with IDs >= 10, the overall sort for trigger-marker payline lists is also
wrong.

#### Cluster Ax4-A: 9 or fewer paylines (not affected by d1)

**Count**: 224 machines

Machines with max payline <= 9 are not affected: string sort and int sort
produce identical results for single-digit IDs. Includes all A_VANILLA 3x3
machines with standard 9-payline configs (M1, M14, M37, etc.), most
B_BCM_WHEEL machines, and all machines with 1 or 5 paylines.

**Named members (sample)**: M1, M14, M37, M272, M274, M275, M279 — all
3x3 BCM machines; all 1-payline machines.

#### Cluster Ax4-B: 10 to 99 paylines (affected by d1)

**Count**: 32 machines (from R0 taxonomy §3 Ax4)

These machines will have misordered `paylines` arrays in
`payouts_by_spin_type` rows for regular pids. The payline_id ordering
shown in the UI panel will be wrong (e.g., "10" appears after "1" and
before "2" rather than after "9").

**Full member list** (measurable: max observed positive line_id in rawdata):

| Machine | Paylines | Archetype (R0 Ax1) |
|---|---|---|
| M87 | 10 | C_FREESPIN_ONLY |
| M123 | 10 | C_FREESPIN_WHEEL |
| M204 | 10 | C_WHEEL_ONLY |
| M209 | 15 | D_MOVE_SPIN |
| M160 | 15 | A_VANILLA |
| M24 | 20 | C_FREESPIN_ONLY |
| M60 | 20 | C_FREESPIN_WHEEL |
| M79 | 20 | C_FREESPIN_ONLY |
| M176 | 20 | C_FREESPIN_WHEEL |
| M199 | 20 | C_FREESPIN_ONLY |
| M212 | 20 | C_FREESPIN_ONLY |
| M67 | 25 | C_FREESPIN_ONLY |
| M117 | 25 | B_BCM_FREESPIN_WHEEL |
| M125 | 25 | B_BCM_FREESPIN_WHEEL |
| M6 | 27 | C_FREESPIN_ONLY |
| M64 | 27 | A_VANILLA |
| M106 | 27 | A_VANILLA |
| M119 | 27 | C_FREESPIN_WHEEL |
| M225 | 27 | C_FREESPIN_WHEEL |
| M5 | 30 | C_FREESPIN_ONLY |
| M88 | 30 | C_FREESPIN_ONLY |
| M108 | 30 | B_BCM_FREESPIN_WHEEL |
| M126 | 30 | B_BCM_FREESPIN_WHEEL |
| M168 | 30 | C_FREESPIN_WHEEL |
| M201 | 30 | C_LOCK_FREESPIN |
| M248 | 30 | B_BCM_FREESPIN_WHEEL |
| M27 | 40 | C_FREESPIN_ONLY |
| M116 | 40 | C_FREESPIN_WHEEL |
| M129 | 40 | C_RESPIN_ONLY |
| M113 | 81 | A_VANILLA (outlier: expanding-symbol engine) |
| M107 | 100 | C_FREESPIN_ONLY |
| M260 | 56 | B_BCM_FREESPIN_WHEEL |

**Spot-check confirmation**: M5 rawdata (mode_1, chunk 1) shows PayoutByPayline
entries with line IDs including two-digit values (e.g., line_id=28 observed in
`rawdata/M5/mode_1/*.json` robot 0 round 2). String keys `"28"`, `"10"`, `"3"`
would sort as `["10","28","3"]` when the correct order is `["3","10","28"]`.
Bug confirmed measurable via Python demonstration:
```
sorted(["1","10","11","2"]) => ["1","10","11","2"]  # wrong
sorted(["1","10","11","2"], key=int) => ["1","2","10","11"]  # correct
```

#### Cluster Ax4-C: 100+ paylines (affected by d1, extreme case)

**Count**: 1 machine (M107, 100 paylines). Included in Ax4-B above.
Specifically called out because string sort divergence is maximal here:
"100" sorts before "2", "9", "99", making the paylines list
completely scrambled.

**Named outlier**: M107 (C_FREESPIN_ONLY, grid=5x3, 100 paylines) — worst
affected by d1 sort bug.

---

### Ax6 Delta: Scatter trigger marker — machines affected by d2 and d3

From R0 taxonomy §3 Ax6, 149 machines have scatter trigger markers:
- **pid=666** (standard): 99 machines
- **Other PIDs** (777, 1001, 5801, 9, 401, 667, 1700, 2600, etc.): 50 machines

The d2 fix (trigger_target alphabetical-first heuristic) and d3 fix
(unique confidence) affect the notes block added to `payout_ids_top20`
rows for these 149 machines.

**Measurable criterion for d2 impact**: any scatter machine where
`scatter_feature_names` (features with non-empty `lengths` in
`all_chains_by_feature`) has 2 or more entries, AND the alphabetically-first
name is NOT the correct primary bonus target.

**Measurable criterion for d3 impact**: any scatter machine where
`scatter_feature_names` has exactly 1 entry (gets `"unique"` instead of
`"data_inferred"`).

#### Sub-cluster Ax6-S1: Standard pid=666 scatter machines

**Count**: 99 machines (listed in full in R0 §3 Ax6)

Key members (BCM archetype most affected by d2/d3):
- B_BCM_FREESPIN_WHEEL: M229, M234, M235, M249, M253, M254, M256, M257, M261, M263, M264, M272, M275
- B_BCM_FREESPIN: M251, M266
- Other scatter machines: M12, M15, M90, M120, M192, M231, M240, M242, M246

#### Sub-cluster Ax6-S2: Non-666 scatter machines

**Count**: 50 machines (listed in full in R0 §3 Ax6)

These machines also receive the notes block with `is_trigger_marker` logic;
d2/d3 apply identically since the logic uses `scatter_marker_pids` set
membership (not hardcoded to pid=666). Includes BCM machines M247, M260,
M262, M264, M273, M274, M276, M279.

#### Sub-cluster Ax6-S3: No scatter marker (not affected by d2/d3)

**Count**: ~107 machines

These machines receive `is_trigger_marker: False` and no
`trigger_target` or `trigger_target_confidence` keys in their
`payout_ids_top20` rows. No change from d2/d3 for this group.

---

### Ax7 (NEW): Bonus feature count — machines affected by d3

This axis is not in R0. It measures the number of entries in
`bonus_chain_dynamics.by_feature` (or equivalently, in the stash's
`scatter_feature_names`) that have non-zero `chain_count`. This
determines whether d3's `"unique"` confidence branch fires.

**Measurable criterion**: count of `by_feature` keys where
`by_feature[feat]["chain_count"] > 0`.

**Spot-check results from cached summaries**:

| Machine | Archetype | by_feature features with data | d3 confidence |
|---|---|---|---|
| M275 | B_BCM_FREESPIN_WHEEL | 2: NormalCollectionSpin (841), NewFreespin (67) | stays `data_inferred` |
| M272 | B_BCM_FREESPIN | 2: NormalCollectionSpin (554), NewFreespin (41) | stays `data_inferred` |
| M274 | B_BCM_WHEEL | 0: by_feature is empty (wheel bonus tracked differently) | no stash data → `unknown` |

**Finding**: Both tested BCM_FREESPIN and BCM_FREESPIN_WHEEL machines have
exactly 2 active features (NormalCollectionSpin + NewFreespin). This is
contrary to the initial intuition that B_BCM_FREESPIN would have 1 feature.

**Implication for d3 scope**:

The `"unique"` confidence branch fires only when `len(scatter_feature_names) == 1`.
Given that both M275 and M272 have 2 active features, the `"unique"` branch
applies to BCM sub-types where the bonus chain resolves to exactly one feature
in `all_chains_by_feature.lengths`. Based on available data:
- B_BCM_WHEEL machines (e.g., M274): by_feature appears **empty** in cached
  summary (wheel spin bonus not tracked as a chain). If `scatter_feature_names`
  is therefore `[]`, these fall into `trigger_target = None, confidence = "unknown"`,
  not `"unique"`.
- B_BCM_FREESPIN_WHEEL and B_BCM_FREESPIN: 2 features observed in both tested
  machines. If this pattern is universal in these sub-types, `"unique"` never
  fires for them under current data.

**Effective d3 scope**: the `"unique"` branch is a dead code path relative to
currently observed fleet data. It would only fire if a machine has exactly 1
feature with non-empty `lengths` in `all_chains_by_feature`. No such machine
was found in the spot-check. This matches the C6 critic finding at
`session_artifacts/_impl/phase_c6/critique.md` line 261-265: `"unique"`
confidence is documented in the spec but never emitted.

**d3 is a correctness invariant fix, not a behavioral fix for existing
machines**: the correct action is to implement `"unique"` in the code when
`len == 1` so the spec and code agree, even if no current machine triggers it.
This prevents future confusion when a single-feature machine is onboarded.

#### Cluster Ax7-A: 0 active features (no chain data)

**Count**: B_BCM_WHEEL machines where wheel-bonus is not tracked as a chain
(e.g., M274). These machines have scatter markers but `scatter_feature_names = []`,
resulting in `trigger_target = None, confidence = "unknown"`. d2/d3 fixes
do not change behavior for this group.

#### Cluster Ax7-B: 1 active feature (target for d3 unique)

**Count**: 0 confirmed from spot-check. This is the hypothetical group where
`"unique"` confidence would fire. Current fleet data shows all BCM machines
with non-empty by_feature have >= 2 features. Future machines onboarded with
single-feature bonus chains would fall here.

#### Cluster Ax7-C: 2+ active features (alphabetical-first heuristic applies)

**Count**: at minimum M275 + M272 = 2 confirmed. Likely applies to the
majority of B_BCM_FREESPIN_WHEEL (20) and B_BCM_FREESPIN (19) machines given
the NCS+NewFreespin pattern in both tested machines.

For d2 specifically: the alphabetical-first pick gives `"NewFreespin"` when
the correct target for the scatter trigger is `"NormalCollectionSpin"` (the
larger chain). This is the bug.

---

## §4 Cross-Axis Similarity Matrix (Carry-forward Delta)

| Fix | Affected Cluster | Archetype (Ax1) | Paylines (Ax4) | Scatter (Ax6) | Feature count (Ax7) | Notes |
|---|---|---|---|---|---|---|
| **d1 sort** | Ax4-B (32 machines) | Mixed: C_FREESPIN_ONLY (15), C_FREESPIN_WHEEL (7), B_BCM_FREESPIN_WHEEL (5), A_VANILLA (3), other (2) | 10-100 paylines | Any (independent of scatter) | N/A | Sort bug is independent of mechanism |
| **d2 trigger_target** | Ax7-C (2+ features) | B_BCM_FREESPIN_WHEEL + B_BCM_FREESPIN | Any | Ax6-S1/S2 (must have scatter) | 2+ | Only machines with scatter AND 2+ features are wrong; single-feature or no-scatter are unaffected |
| **d3 unique confidence** | Ax7-B (1 feature) | Unknown (no current machine confirmed) | Any | Ax6-S1/S2 (must have scatter) | Exactly 1 | Dead code path for current fleet; needed for future correctness |
| **d4 avg_bonus_payout** | All BCM machines | B_BCM_* (57 base machines) | Any | Any | Any | Behavioral change: None vs 0.0 for machines where bonus feature is unresolved |

**Co-clustering pattern**: d1 and d2/d3 are fully **orthogonal** — a machine
can be affected by both (e.g., M117: 25 paylines + pid=666 scatter) or only
one. The d4 fix affects the entire BCM family regardless of payline count or
scatter presence.

**Overlap for d1 + Ax6-S1** (machines affected by both sort bug AND scatter):
From the Ax4-B list that also appear in Ax6-S1 (pid=666):

M67, M79, M88, M95, M96, M107, M109, M114, M116, M117, M119, M120, M121,
M125, M134, M165, M166, M167, M176, M178, M179, M180, M181, M183, M184,
M185, M199, M200, M202, M204, M210, M212 — cross-referencing Ax4-B with
Ax6-S1 yields approximately 15-20 machines affected by both d1 and d2/d3.

For these machines, both the paylines sort order in `payouts_by_spin_type`
and the trigger_target in `payout_ids_top20` notes need correction.

---

## §5 Outlier Inventory (Carry-forward Delta)

| Machine | Fix | Outlier reason |
|---|---|---|
| **M107** | d1 | 100 paylines — worst affected by sort bug; string sort of `"1"`..`"99"`.."100"` produces near-completely wrong order; paylines panel will appear severely scrambled for this machine |
| **M113** | d1 | 81 paylines; also outlier in Ax1 (expanding-symbol engine) — the sort bug manifests but the machine is already a Tier-1 hard case for other reasons |
| **M260** | d1 + potentially d2 | 56 paylines AND in Ax6-S2 (non-666 scatter) AND B_BCM_FREESPIN_WHEEL; 70-90% fallback in BCM sweep (per R0 §5); affected by sort bug, scatter marker, AND BCM attribution issues — highest complexity intersection |
| **M274** | d2/d3 | B_BCM_WHEEL with scatter marker but `by_feature = {}` (wheel-spin bonus not tracked as chain) — scatter marker points to a non-chain bonus; `trigger_target = "unknown"` both before and after d2 fix; the fix leaves this machine unchanged |
| **M275** | d2 | Primary example of the alphabetical-first bug: scatter pid=666 with `scatter_feature_names = ["NewFreespin", "NormalCollectionSpin"]` (alphabetically sorted); d2 picks `"NewFreespin"` but `"NormalCollectionSpin"` is the primary target (841 vs 67 chain count); mechanism_registry inverse mapping would resolve correctly |
| **M14** | d4 | Non-BCM vanilla machine; `avg_bonus_payout` is `None` (no BCM bonus feature). The behavioral change from 0.0 → None already occurred in C5; frontend `!= null` guard confirmed safe at `app.js:6196` |

---

## §6 d4: `avg_bonus_payout` — Downstream Consumer Inventory

The d4 fix concerns the behavioral delta between `None` and `0.0` for
`summary["collect_mechanic"]["bonus_cycle_correction"]["avg_bonus_payout"]`.
This is the most backend-impacting of the 4 Cluster D fixes.

### Where `avg_bonus_payout` is written

**Source 1** (PIA inline, the current code path):
`fresh_slotlab/player_impact_analyzer.py` line 4817-4824 — nested lambda
expression. When `_cm_bonus_feat` is None, the outer
`if _cm_bonus_feat else None` branch returns `None`.
When `_cm_bonus_feat` is not None but `total_completed_cycles == 0`,
inner `if total_completed_cycles > 0 else None` returns `None`.
When both conditions are met, returns `bonus_total_win / total_completed_cycles`.

**Source 2** (`parser.py` internal helper):
`fresh_slotlab/analyzer/core/parser.py` line 323 — inside
`_compute_bonus_correction()`. Local variable `avg_bonus_payout` used only
for the correction formula; NOT written to the summary dict directly (it is
internal to the computation function). This is not a consumer.

### Downstream consumers (all readers of `avg_bonus_payout` from summary)

| Consumer | Location | Access path | Null-safe? | Impact of None |
|---|---|---|---|---|
| **Frontend renderer** | `src/web_console/frontend/app.js:6196` | `bcc.avg_bonus_payout != null ? Number(...) : "—"` | Yes — explicit `!= null` guard | Displays `"—"` (dash) instead of `"0"` — correct semantic change |
| **Backend test** | `tests/backend/test_full_pipeline_m272.py:391` | `assert k in bcc` — only checks key presence, not value | N/A — checks structure only | No impact; test verifies key exists, not that it is non-None |
| **Collect mechanic test** | `tests/analyzer/test_c5_collect_mechanic_plugin.py:298` | Sets `"avg_bonus_payout": 40.0` in fixture | N/A — sets value, doesn't read None | No impact; test fixture uses a concrete float |
| **Gap6 test** | `tests/analyzer/test_c5_gap_6_chunk_spin_times_recommendation.py:257` | Same fixture pattern | N/A | No impact |
| **`_compute_bonus_correction` caller** | `fresh_slotlab/player_impact_analyzer.py` | Reads `all_cycles_peaks`, `all_final_cc_values`, `upstream_feature_tally` — NOT `avg_bonus_payout` from summary | N/A | The correction formula recomputes avg internally; does not read the summary field |

**Finding**: The only active downstream reader of `avg_bonus_payout` from the
summary JSON is the frontend (`app.js:6196`). It is already null-safe with an
explicit `!= null` guard. The behavioral change (displaying `"—"` instead of
`"0"` for machines with no resolved bonus feature) is semantically correct.
No backend logic reads `avg_bonus_payout` from the summary to make decisions;
the correction formula in `parser.py` recomputes the average independently.

**The d4 fix is frontend-display-only in its behavioral impact**: zero backend
routing, zero test infrastructure failure, zero cascade effect on other summary
fields. The only observable change is the displayed string in the collect
mechanic panel for non-BCM or misconfigured machines.

### Machines affected by d4 behavioral change

`avg_bonus_payout` is `None` (correct) vs `0.0` (previous behavior) when
`_cm_bonus_feat` is None OR `total_completed_cycles == 0`. From R0 taxonomy:

- **All non-BCM machines** (199 base machines): no BCM collect mechanic;
  `collect_mechanic.applicable = false`; `bonus_cycle_correction` block still
  present in schema but `applicable = false`. `avg_bonus_payout = None` is
  correct (no bonus feature identified). Previously showed `0.0`.

- **BCM machines with unresolved bonus feature** (estimated 5-10 machines):
  `_cm_bonus_feat` could not be resolved from `bcm_pairings.json` or heuristic.
  These machines show `None` correctly.

- **BCM machines with resolved bonus feature but 0 completed cycles**: sample
  too small to observe a full BCM cycle. `avg_bonus_payout = None` (no data).
  Previously showed `0.0`.

The behavioral delta is confined to the display layer. No backend cache
invalidation, no hash change (behavior was already `None` in C5 per the
critique at `session_artifacts/_impl/phase_c5/critique.md:118`).

---

## §7 d1 Spot-Check: Payline IDs in Rawdata

The following spot-check confirms that `PayoutByPayline` in rawdata produces
string payline keys through the parser pipeline, and that two-digit IDs exist
in the affected machines:

| Machine | Observed PayoutByPayline format | Two-digit line_ids confirmed | Sort bug fires |
|---|---|---|---|
| M5 (30 paylines) | `"3:9-9(101,201,301,); 7:9-9(100,201,301,); 18:8-8(...);"` | Yes: line_ids 10, 18, 20, 23, 27, 28 observed in first 10 rounds | Yes |
| M27 (40 paylines) | String format confirmed; chunks present | Expected (40-payline machine) | Yes |
| M107 (100 paylines) | Chunks present; format confirmed | Expected (100-payline machine) | Yes — extreme case |
| M113 (81 paylines) | Chunks present; expanding-symbol engine | Expected | Yes |
| M260 (56 paylines) | Chunks present; B_BCM_FREESPIN_WHEEL | Expected | Yes |

**Root cause** (measured): `parser.py` line 1869 stores payline keys as
`str(_c3lid)` where `_c3lid` is `int`. The plugin `emit()` sorts these string
keys at lines 424 and 431 using `key=lambda x: x["payline_id"]` which is
string comparison. The int carve-out for `-1` is not implemented.

**Fix scope** (measurable): lines 424 and 431 in
`fresh_slotlab/analyzer/features/payouts_by_spin_type.py`. Two sort calls,
same fix: `key=lambda x: int(x["payline_id"])`. The `-1` carve-out mentioned
in the brief is already handled correctly by string sort (since `"-1"` < `"0"`
in ASCII, it sorts first, which is correct); however, once any 2-digit ID
appears alongside it, the combined sort breaks. The correct fix is `int()` with
no special-casing for `-1` since `int("-1") = -1 < 1`.

---

## §8 d2 Spot-Check: trigger_target Alphabetical-First Bug

**Confirmed from M275 cached summary** (`cache/final_verify/M275/player_impact_summary.json`):

```
payout_ids_top20 row for pid=666:
  is_trigger_marker: True
  trigger_target: "NewFreespin"      # WRONG
  trigger_target_confidence: "data_inferred"
```

**Root cause** (`bonus_chain_dynamics.py` lines 205-207):

```python
if scatter_marker_pids and scatter_feature_names:
    trigger_target = sorted(scatter_feature_names)[0]   # alphabetical-first
    trigger_target_confidence = "data_inferred"
```

`scatter_feature_names` for M275 is built in `player_impact_analyzer.py`
lines 4864-4867 by filtering `all_chains_by_feature` for features with
non-empty `lengths`. For M275:
- `NormalCollectionSpin`: chain_count=841
- `NewFreespin`: chain_count=67

Both have non-empty `lengths` in the local variable (even though the emitted
summary computes quantiles rather than storing raw lengths). Alphabetical sort
gives `["NewFreespin", "NormalCollectionSpin"]`, and `[0]` picks `"NewFreespin"`.

The correct target is `NormalCollectionSpin` — the mechanism that the scatter
trigger (pid=666) directly initiates, which is identifiable from
`mechanism_registry.scatter_marker_pids`. The brief states the fix should
"use mechanism_registry.scatter_marker_pids inverse mapping" — the registry
associates a scatter PID with its triggering bonus feature directly, avoiding
the alphabetical ambiguity.

**Same pattern confirmed for M272**: `scatter_feature_names` has both
`NormalCollectionSpin` (554 chains) and `NewFreespin` (41 chains), so M272
also receives `"NewFreespin"` as wrong `trigger_target`.

**Fleet scope of d2 bug**: all machines in Ax7-C (2+ active features in
`scatter_feature_names`) that have scatter markers. This is at minimum
M275 and M272; likely extends to most B_BCM_FREESPIN_WHEEL machines
and many B_BCM_FREESPIN machines given the NCS+NewFreespin pattern observed
in both tested machines.

---

## §9 Summary of Fleet Subsets Per Fix

| Fix | Affected subset | Count (base machines) | Measurable criterion |
|---|---|---|---|
| **d1 paylines sort** | Machines with 10+ paylines (Ax4-B + Ax4-C) | **32 machines** | max positive line_id >= 10 in rawdata PayoutByPayline |
| **d2 trigger_target** | Scatter machines with 2+ active bonus features (Ax6-S1/S2 ∩ Ax7-C) | **~37 machines** (99+50 scatter minus Ax7-A empty-feature machines; Ax7-B zero confirmed) | pid in scatter_marker_pids AND len(scatter_feature_names) >= 2 |
| **d3 unique confidence** | Scatter machines with exactly 1 active bonus feature (Ax6-S1/S2 ∩ Ax7-B) | **0 confirmed current machines** (dead branch for current fleet) | pid in scatter_marker_pids AND len(scatter_feature_names) == 1 |
| **d4 avg_bonus_payout** | All non-BCM machines + BCM machines with unresolved/zero-cycle bonus | **~199+ machines** (all where _cm_bonus_feat is None) | collect_mechanic.bonus_cycle_correction.avg_bonus_payout was 0.0, now None |

---

## §10 Suggested Groupings for Plugin Architecture (Cluster D)

These are observable seams where the fixes have natural scope boundaries. The
designer decides how to express them architecturally.

### Seam D1: Paylines sort — universal fix, no machine grouping needed

The sort fix is a 2-line change in `payouts_by_spin_type.py` that applies to
all machines uniformly. No machine-specific or archetype-specific logic is
needed. The fix is self-contained in the emit() method. No new plugin or
registry entry required.

Natural scope: single file (`payouts_by_spin_type.py` lines 424, 431), two
identical lambda changes, covers all 32 affected machines without any
per-machine awareness.

### Seam D2+D3: trigger_target — mechanism_registry dependency

The fix requires the `bonus_chain_dynamics` plugin's emit() to use
`mechanism_registry.scatter_marker_pids` inverse mapping (associating a
scatter PID with its triggering feature name). This means the mechanism
registry must store or provide a lookup from `pid → triggering_feature_name`.

The fix scope stays within `bonus_chain_dynamics.py` emit() — no new plugin
needed. The registry is already available as `ctx.mechanism_registry`. The
question for the designer is whether the inverse mapping is:
- Pre-computed and stored in the mechanism registry object, or
- Derived at emit() time from the stash's chain data (chain counts as proxy
  for "primary" feature)

The `"unique"` confidence (d3) is a spec alignment fix: add an
`elif len(scatter_feature_names) == 1` branch emitting `"unique"` before the
`else` (multiple features) emits `"data_inferred"`. No fleet machine currently
triggers this but the spec says it should exist.

### Seam D4: avg_bonus_payout None-safety — frontend display only

The fix scope is entirely within `collect_mechanic.py` or the PIA inline
block: ensure the formula returns `None` not `0.0` when bonus feature is
unresolved. The frontend is already null-safe. No new plugin, no registry
change, no schema version bump required (the value was already `None` in C5
for M14 and other non-BCM machines per critique §9). The fix formalizes the
existing behavior as the spec.

---

*Taxonomy complete. Fleet size 256 base + 166 variants = 422 total. 32 machines
affected by d1 (paylines sort). ~37 by d2 (trigger_target wrong for 2-feature
scatter machines). 0 current machines trigger d3 (unique confidence is dead
branch for current fleet). ~199+ machines display behavioral delta from d4
(None vs 0.0, frontend-only impact).*
