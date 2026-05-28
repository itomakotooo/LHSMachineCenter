# 06 — Validation: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Role**: arch-validator (W3)
> **Input artifacts**: `04_architecture_proposal.md`, `00_brief.md`, `02_taxonomy.md`,
>   `03_coupling_audit.md`, source code, cached summaries
> **Output**: `session_artifacts/_arch_carryforward_r1/06_validation.md`
> **Method**: Walk 8 concrete cases through the proposal; run real commands against
>   existing code and cached summaries; actively search for missed test updates.

---

## §0 Commands Run

All findings below are grounded in real command output, not abstract reasoning.

**Test suite baseline:**
```
pytest tests/analyzer/                  -> 612 passed, 3 skipped
pytest tests/analyzer/test_c3_5_isolation_m275_only.py test_c3_5_m14_no_multiplier_wild.py
                                        -> 25 passed
pytest tests/analyzer/test_c6_bonus_chain_dynamics_plugin.py
                                        -> 33 passed
pytest tests/analyzer/test_c6_gap_3_pid_666_trigger_marker.py
                                        -> 10 passed
```

**Effective version reads:**
```python
compute_base_analyzer_version()                     -> "fa440e3eb5f6"
compute_effective_version_for_machine("M275", 1)    -> "5c78f3834a1e"
compute_effective_version_for_machine("M14",  1)    -> "6aae41144cea"
compute_effective_version_for_machine("M37",  1)    -> "6aae41144cea"
compute_effective_version_for_machine("M272", 1)    -> "6aae41144cea"
compute_effective_version_for_machine("M11",  1)    -> "6aae41144cea"
```

**Plugin set reads (from manifests):**
```
M275: [payouts_by_spin_type, reel_marginal_by_spin_type, bankruptcy_simulation,
       multiplier_profile, multiplier_wild, machine_mechanics,
       upstream_feature_breakdown, collect_mechanic, bonus_chain_dynamics]  # 9 plugins
M14:  [payouts_by_spin_type, reel_marginal_by_spin_type, bankruptcy_simulation,
       multiplier_profile, machine_mechanics, upstream_feature_breakdown,
       collect_mechanic, bonus_chain_dynamics]  # 8 plugins (no multiplier_wild)
M37, M272, M11: identical to M14  # 8 plugins
```

**d1 sort bug demonstration:**
```python
sorted(["1","10","11","2","20","3"])         -> ["1","10","11","2","20","3"]  # WRONG
sorted(["1","10","11","2","20","3"], key=int) -> ["1","2","3","10","11","20"]  # CORRECT
sorted(["-1","1","10","2","20"])              -> ["-1","1","10","2","20"]  # string: ok for -1 but wrong for 10
sorted(["-1","1","10","2","20"], key=int)     -> ["-1","1","2","10","20"]  # CORRECT
```

**d2 chain-count majority vote verification:**
```python
# M275: NCS=841, NF=67
sorted(["NewFreespin","NormalCollectionSpin"])[0]                             -> "NewFreespin"  # current WRONG
max(["NewFreespin","NCS"], key=lambda f: {"NewFreespin":67,"NCS":841}[f])     -> "NCS"          # proposed CORRECT

# M272: NCS=554, NF=41
max(["NF","NCS"], key=lambda f: {"NF":41,"NCS":554}.get(f,0))                -> "NCS"          # proposed CORRECT
```

**d2 tie-breaking edge case:**
```python
# Tie: ZFeature, AFeature both count=0
max(["ZFeature","AFeature"], key=lambda f: {}.get(f,0))  -> "ZFeature"  # first in list wins
max(["AFeature","ZFeature"], key=lambda f: {}.get(f,0))  -> "AFeature"  # first in list wins
# PIA stash uses sorted() so list is always ["AFeature","ZFeature"] -> AFeature wins on tie
# But unit test fixture does NOT sort -> ["ZFeature","AFeature"] -> ZFeature wins -> BREAK B2
```

**Cached summary reads:**
```
cache/final_verify/M275/player_impact_summary.json:
  payout_ids_top20[pid=666].notes.trigger_target = "NewFreespin"  <- BUG confirmed
  collect_mechanic.bonus_cycle_correction.avg_bonus_payout = 555179.6875
  collect_mechanic.applicable = True

cache/final_verify/M14/player_impact_summary.json:
  collect_mechanic.applicable = False
  collect_mechanic.bonus_cycle_correction.avg_bonus_payout = None  <- already correct

cache/c1_verify/M272_post/player_impact_summary.json:
  bonus_chain_dynamics.by_feature keys: ["NormalCollectionSpin","NewFreespin"]
```

**PIA control flow positions:**
```
PIA:5042 try: _topological_sort(...)
PIA:5044 except (_PluginCyclicDependencyError, _PluginMissingDependencyError):
PIA:5058     summary["analyzer_init_error"] = _topo_error_dict
PIA:5065     raise SystemExit(1)            <-- JSON NOT YET WRITTEN (bug)
...
PIA:5210 out_json = write_summary_json(...)  <-- too late; unreachable on error path
```

**Gap-3 test trigger_target assertion (the missed break):**
```python
# tests/analyzer/test_c6_gap_3_pid_666_trigger_marker.py:160
assert notes.get("trigger_target") == "NewFreespin"  # will FAIL after d2
# Proposal §7: "No change needed for this test" -- INCORRECT
```

---

## §1 Representatives Picked

8 cases were walked. All 8 are listed here with selection rationale.

| Case | Machine | Taxonomy cluster | Why selected |
|---|---|---|---|
| 1 | M275 | Ax7-C (2-feature BCM_FREESPIN_WHEEL) | Driving case for d2 correctness; has scatter (d2/d3), <10 paylines (d1 latent), real avg_bonus_payout (d4), 9 plugins (Cluster E isolation) |
| 2 | M272 | Ax7-C (2-feature BCM_FREESPIN) | Same d2 pattern as M275 but different archetype; confirms cross-archetype heuristic generalizes |
| 3 | M14 | Ax4-A (9 paylines) + Ax6-S3 (no scatter) | Vanilla baseline; represents 224 unaffected machines; d4 None path; isolation invariant anchor |
| 4 | M37 | A_VANILLA 1-payline classic | Single payline edge case; all fixes inapplicable; Cluster A try/finally success-path |
| 5 | M11 | B_BCM jackpot_ids via raw field | Covers C4-era concern; all D fixes inapplicable; verifies no false-positive effects |
| 6 | Hypothetical 50-payline machine (M27 proxy) | Ax4-B (10+ paylines, 40 paylines confirmed for M27) | Covers d1 real impact; demonstrates string-vs-int divergence concretely |
| 7 | Hypothetical single-scatter-feature machine | Ax7-B (1 feature, 0 confirmed current) | Covers d3 dead branch; future-machine correctness |
| 8 | Cluster E test migration walk | Test infrastructure | Covers differential assertion correctness and inject-bug recipe validity |

**Selection coverage**: Cases 1–5 cover fleet archetypes from taxonomy Ax7-C (2 cases), Ax4-A + no-scatter (1 case), 1-payline classic (1 case), C4-era BCM (1 case). Cases 6–7 cover the two real-impact hypothetical scenarios the proposal depends on. Case 8 covers the test refactor infrastructure.

---

## §2 Per-Case Walkthrough

### Case 1: M275 (driving case)

**M275 plugin set**: `payouts_by_spin_type`, `reel_marginal_by_spin_type`, `bankruptcy_simulation`,
`multiplier_profile`, `multiplier_wild`, `machine_mechanics`, `upstream_feature_breakdown`,
`collect_mechanic`, `bonus_chain_dynamics` — **9 plugins**.

**Hash** (pre-fix): `effective_analyzer_version = "5c78f3834a1e"`, `base_hash = "fa440e3eb5f6"`.

#### Phase ordering: E → D → A

**Cluster E first**: Replace pin assertions with differential assertions. M275's current pin `"5c78f3834a1e"` is removed. The structural assertion `m275_ev != m14_ev` is added. At this point no code has changed, so the effective versions are still the current values and both old and new assertions pass.

**Cluster D second**: Four fixes applied. For M275:

**d1 (paylines int sort)**

Today: M275 has paylines 1–5 (confirmed from cache). String sort and int sort produce identical output for single-digit IDs. No behavioral change.

After D-1: `payouts_by_spin_type.py` bytes change → M275 EV flips from `"5c78f3834a1e"` to a new value. The differential assertion `m275_ev != m14_ev` still holds (M275's 9-plugin composition still differs from M14's 8-plugin composition; the sort fix doesn't add or remove any plugin from the manifest).

**d2 (trigger_target correctness)**

Today (confirmed by Bash read of `cache/final_verify/M275`):
```
trigger_target = "NewFreespin"   <- WRONG (alphabetical pick)
trigger_target_confidence = "data_inferred"
```

Stash currently has `scatter_feature_names = ["NewFreespin", "NormalCollectionSpin"]` (sorted, so alphabetical). The current `sorted(scatter_feature_names)[0]` = `"NewFreespin"`.

Under proposal: PIA F6 inline block extended to also compute:
```python
"scatter_feature_chain_counts": {
    "NormalCollectionSpin": 841,  # from all_chains_by_feature["NCS"]["lengths"]
    "NewFreespin": 67,
}
```

Plugin emit() picks:
```python
max(["NewFreespin","NormalCollectionSpin"],
    key=lambda f: {"NormalCollectionSpin": 841, "NewFreespin": 67}.get(f, 0))
-> "NormalCollectionSpin"   # CORRECT
```

**d3 (trigger_target_confidence)**: `len(scatter_feature_names) == 2` → else branch → stays `"data_inferred"`. No change.

**d4 (avg_bonus_payout)**: `avg_bonus_payout = 555179.6875` (win_sum >> 0). `s > 0` guard passes. Same float result. No behavioral change.

**Cluster A third**: Error surfacing try/finally. M275 has no cyclic dependencies. Success path is entirely unchanged.

**Summary JSON snippets (post-D, M275):**
```json
{
  "effective_analyzer_version": "<new-hash-after-d1-d2>",
  "player_impact": {
    "payout_ids_top20": [
      {
        "payout_id": "666",
        "notes": {
          "is_trigger_marker": true,
          "trigger_target": "NormalCollectionSpin",
          "trigger_target_confidence": "data_inferred"
        }
      }
    ]
  },
  "collect_mechanic": {
    "bonus_cycle_correction": {
      "avg_bonus_payout": 555179.6875
    }
  }
}
```

**Migration**: Fresh report generation required. Old report still servable (frontend doesn't render `trigger_target`).

**Verification checklist**:
- d1: `paylines` for M275 STs are `["1","2","3","4","5"]` before and after — no change
- d2: `trigger_target = "NormalCollectionSpin"` in fresh report
- d3: `trigger_target_confidence = "data_inferred"` (unchanged)
- d4: `avg_bonus_payout = 555179.6875` (unchanged)
- Cluster E: `m275_ev != m14_ev` holds after D

**Verdict: pass** (see §3 for test-update gap B1 found during this walkthrough)

---

### Case 2: M272 (BCM_FREESPIN, same d2 pattern)

**M272 plugin set**: Identical to M14 (8 plugins, no `multiplier_wild`). `effective_analyzer_version = "6aae41144cea"`.

**M272 taxonomy data** (confirmed from `cache/c1_verify/M272_post/player_impact_summary.json`):
- `bonus_chain_dynamics.by_feature` keys: `["NormalCollectionSpin", "NewFreespin"]`
- NCS chain count: 554, NewFreespin chain count: 41

**Phase E → D → A walkthrough:**

**Cluster E**: M272 EV is the same as M14 (`"6aae41144cea"`). The proposed `test_m14_m37_m272_share_effective_version` assertion covers M272 directly. Post-D-1, all three machines still share the same (new) EV since they have identical plugin sets.

**d2 (trigger_target)**: Current behavior per taxonomy §8: alphabetical pick gives `"NewFreespin"` (WRONG for M272 just like M275). Post-fix: `max(chain_counts)` with NCS=554 > NF=41 → `"NormalCollectionSpin"` (correct).

**d2 test impact**: `tests/backend/test_full_pipeline_m272.py` — Grep confirms no `trigger_target` in this file. The M272 backend test checks structural presence of fields, not values. No test break from the M272 correction.

**d2 cross-archetype verification**: M275 is `BCM_FREESPIN_WHEEL`, M272 is `BCM_FREESPIN`. Both have the same `NCS+NewFreespin` pattern with NCS as the dominant chain. The majority-vote heuristic generalizes correctly across these two archetypes.

**All other fixes**: d1 (M272 has < 10 paylines per taxonomy Ax4-A member list), d3 (2 features → stays `data_inferred`), d4 (M272 has concrete avg_bonus_payout like M275).

**Verification checklist**:
- No test asserts M272's specific `trigger_target` value → no test break
- Cluster E differential assertions include M272 → covered

**Verdict: pass**

---

### Case 3: M14 (vanilla baseline)

**M14 plugin set**: 8 plugins (no `multiplier_wild`). `effective_analyzer_version = "6aae41144cea"`.

**Phase E → D → A walkthrough:**

**Cluster E**: `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` pinned at lines 109 and 241 in two test files. After D-1 or D-2+D-3, both pins break. Differential assertion replaces with `m14_ev == m37_ev == m272_ev` — structural, immune to D-phase version flips.

**d1 (paylines)**: M14 has 9 paylines. Payline IDs 1–9. String sort and int sort are identical for single-digit IDs. Confirmed from `cache/final_verify/M14`. No behavioral change.

**d2 (scatter)**: No `scatter_marker_pids` in M14 manifest. `if scatter_marker_pids and scatter_feature_names:` branch never fires. All payout_ids_top20 rows get `is_trigger_marker=False`. No change.

**d4 (avg_bonus_payout)**: `_cm_bonus_feat = None` (M14 is non-BCM, `applicable=False`). Outer `if _cm_bonus_feat else None` returns `None` directly. The `s > 0` guard is never reached. No change.

**Cluster A**: M14 has no cyclic dependencies. No DECLARED_DEPS errors. Success path is unchanged. The 14 test assertions for `"analyzer_init_error" not in summary` on M14's success path remain GREEN.

**Hash trace**: Post D-1, M14 EV flips from `"6aae41144cea"` to a new value. Post D-2+D-3, it flips again (or once if in same commit). The differential assertion `m14_ev == m37_ev == m272_ev` holds both times — all three have identical 8-plugin sets.

**Verification checklist**:
- `avg_bonus_payout`: already `None`, no change
- `feature_errors`: absent (success path), unaffected
- `analyzer_init_error`: absent (success path), unaffected
- Cluster E differential assertions: PASS

**Verdict: pass**

---

### Case 4: M37 (single-payline classic)

**M37 plugin set**: Identical to M14 (8 plugins). `effective_analyzer_version = "6aae41144cea"`.

**Phase E → D → A walkthrough:**

**d1**: From cached summary, M37's payout_ids in `payouts_by_spin_type` have `paylines: []` (empty list). Sort of empty list is a no-op regardless of key function. No change.

**d2, d3**: No scatter markers. Not applicable.

**d4**: M37 is not BCM. `_cm_bonus_feat = None`. Already emits `None`. No change.

**Cluster A**: No production errors. Success path unchanged.

**Cluster E**: M37's EV is part of the `test_m14_m37_m272_share_effective_version` assertion. Structural — survives D commits.

**Why M37 is included**: M37 is the "classic 1-payline Seven" machine that is a known outlier (1 payline, all other machines have 5+). It confirms the proposal doesn't break on machines where `paylines` data is legitimately empty.

**Verdict: pass**

---

### Case 5: M11 (jackpot_ids via raw field)

**M11 plugin set**: Identical to M14 (8 plugins). `effective_analyzer_version = "6aae41144cea"`.

**Manifest check** (confirmed): M11 has no `scatter_marker_pids` override, no `jackpot_ids` override. Machine mechanics reads both from raw data. This is the "C4-era raw-field" pattern.

**Phase E → D → A walkthrough:**

**All D fixes**: Not applicable. No 10+ paylines (so d1 is latent), no scatter markers (d2/d3 don't fire), no BCM with zero win (d4 doesn't change behavior).

**Cluster A**: No active errors in production. All 14 success-path `"analyzer_init_error" not in summary` assertions include `test_c4_m11_jackpot_ids_union.py:133`. After Cluster A, the success path does not write `analyzer_init_error`. Assertion remains GREEN.

**Cluster E**: M11 EV = `"6aae41144cea"` (same as M14). Not in the `test_m14_m37_m272_share_effective_version` assertion — but the structural property (M11 has 8 plugins, same as M14) holds. Not breaking.

**Verification checklist**:
- All 14 no-`analyzer_init_error` assertions: GREEN on success path
- M11's jackpot_ids pattern: unaffected (machine_mechanics plugin not changed)

**Verdict: pass**

---

### Case 6: Hypothetical 50-payline machine (d1 real case, M27 proxy)

This case exercises the d1 fix on a machine from Ax4-B. M27 (40 paylines, confirmed) is the concrete fleet representative. The 50-payline count is synthetic for illustration; the behavior is identical at 40.

**Pre-d1 behavior** (string sort, demonstrated):
```python
sorted(["1","10","11","2","20","3","30","4","40","5","50"])
-> ["1","10","11","2","20","3","30","4","40","5","50"]   # WRONG
```
The `paylines` array in on-disk summaries for M27 has this misordered content.

**Post-d1 behavior** (int sort):
```python
sorted(["1","10","11","2","20","3","30","4","40","5","50"], key=int)
-> ["1","2","3","4","5","10","11","20","30","40","50"]   # CORRECT
```

**M107 (100 paylines) as extreme outlier** (from taxonomy Ax4-C): String sort puts `"100"` before `"2"`, `"9"`, `"99"` — the paylines panel is completely scrambled. The int-sort fix is especially valuable here. Confirmed by running:
```python
sorted(["1","10","100","11","2","20","3"])       # ["1","10","100","11","2","20","3"] WRONG
sorted(["1","10","100","11","2","20","3"], key=int)  # ["1","2","3","10","11","20","100"] CORRECT
```

**Trigger-marker path** (for machines with scatter PIDs): The `-1` sentinel sorts correctly in both string and int modes:
- String: `["-1","1","10","2"]` — `"-"` < `"0"` so `-1` is first (correct)
- Int: `int("-1") = -1 < 1`, so `-1` is first (also correct)
The proposal's recommendation to use `int()` directly (without special-casing `-1`) is sound: `int("-1") = -1` sorts before all positive integers.

**Silent dependency note** (03 §6.2): The `int()` call raises `ValueError` for any non-integer payline_id. Per all audited machines, payline_ids are always int-parseable. The proposal correctly says this should produce an early-signal error for a future machine with non-numeric payline labels.

**Hash trace**: `payouts_by_spin_type.py` bytes change. All 253 machines get new EV. Ax4-B machines (32 of them) produce wrong paylines order in old reports. Old reports servable (no crash). Regen required for correct display.

**Test coverage gap**: No existing test covers a 10+ payline fixture machine. A new test using M107 or M5 cached chunks is needed (proposal §5.1 states this but does not specify which fixture to use). Without it, the inject-bug recipe (revert to string sort) cannot produce a RED test for current fixture machines.

**Verdict: pass** (fix is correct; backward-compat partial — 32 machines need regen; new test required)

---

### Case 7: Hypothetical single-scatter-feature machine (d3)

This case exercises the `"unique"` confidence branch, which is dead code for the current fleet (0 confirmed machines with exactly 1 active scatter feature in `all_chains_by_feature`).

**Pre-d3 behavior**:
```python
scatter_feature_names = ["OnlyFeature"]  # len=1
if scatter_marker_pids and scatter_feature_names:
    trigger_target = sorted(scatter_feature_names)[0]   # "OnlyFeature" (correct by accident)
    trigger_target_confidence = "data_inferred"          # WRONG: should be "unique"
```
The trigger_target is accidentally correct, but the confidence is wrong: with only one possible feature, `"data_inferred"` is semantically incorrect — it implies uncertainty, but there is none.

**Post-d3 behavior** (combined with d2 in same code block, per proposal §5.2):
```python
if len(scatter_feature_names) == 1:
    trigger_target = scatter_feature_names[0]   # "OnlyFeature"
    trigger_target_confidence = "unique"        # CORRECT
else:
    # d2: chain-count majority vote
    trigger_target = max(scatter_feature_names,
                         key=lambda f: _chain_counts.get(f, 0))
    trigger_target_confidence = "data_inferred"
```

**D3 confirmation**: The proposal is correct that d3 does not fire for M275 or M272 (both have 2 features → `len == 2` → else branch). M275 stays `"data_inferred"`. The d3 fix is purely a future-machine correctness guarantee.

**No existing report affected**: Taxonomy Ax7-B has 0 confirmed members. Old reports do not need regen.

**New test required**: A unit test with `scatter_feature_names = ["OnlyFeature"]` asserting `trigger_target_confidence == "unique"`. Inject-bug: remove `len == 1` branch → gets `"data_inferred"` → RED.

**Verdict: pass** (fix is correct; 0 backward-compat impact; new test required)

---

### Case 8: Cluster E test migration walk

**Pre-migration state**: Three pinned constants in two test files:
- `test_c3_5_isolation_m275_only.py:93`: `_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"`
- `test_c3_5_isolation_m275_only.py:109`: `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"`
- `test_c3_5_m14_no_multiplier_wild.py:241`: `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` (local)

**Effect of D-1 on current tests**: `payouts_by_spin_type.py` bytes change → ALL machines' EVs flip → `"5c78f3834a1e"` is wrong for M275 and `"6aae41144cea"` is wrong for M14/M37/M272 → 3 assertion sites turn RED.

**Effect of D-2+D-3 on current tests**: `bonus_chain_dynamics.py` bytes change → same cascade (C6 added this plugin to all 253 machines) → same 3 sites turn RED.

**Why ordering matters**: Cluster E must commit BEFORE Cluster D. If D commits while the pin-assertion tests exist, CI is RED between D and E commits. The 3-commit E → D → A sequence prevents this.

**Post-migration state (differential assertions)**:

File 1 (`test_c3_5_isolation_m275_only.py`) replacement shape:
```python
def test_m275_effective_version_differs_from_m14():
    """M275 has multiplier_wild; M14 does not. Their EVs must differ."""
    m275_ev = _compute_effective_version("M275", 1)
    m14_ev  = _compute_effective_version("M14",  1)
    assert m275_ev != m14_ev

def test_m14_m37_m272_share_effective_version():
    """Machines with identical plugin sets must have identical EVs."""
    m14_ev  = _compute_effective_version("M14",  1)
    m37_ev  = _compute_effective_version("M37",  1)
    m272_ev = _compute_effective_version("M272", 1)
    assert m14_ev == m37_ev
    assert m14_ev == m272_ev
```

After D-1: `m275_ev = NEW_M275_EV`, `m14_ev = NEW_M14_EV`. Both differ because M275 has 9 plugins and M14 has 8. `m14_ev == m37_ev == m272_ev` because all three have identical 8-plugin sets. Both assertions PASS.

After D-2+D-3: Same reasoning — plugin count difference preserved.

**`_C3_BASE_HASH = "fa440e3eb5f6"`**: KEPT hardcoded (no change). `compute_base_analyzer_version()` reads `core/*.py` bytes only — none of which are changed by D-fixes. Confirmed: `compute_base_analyzer_version()` returns `"fa440e3eb5f6"`. This pin retains its regression guard property against accidental `core/*.py` modifications.

**Inject-bug recipe verified (non-trivial proof)**:
```
Step 1: Add "multiplier_wild" to M14.json analyzer_features list
Step 2: Run test_m275_effective_version_differs_from_m14
Step 3: M14 EV now incorporates multiplier_wild hash -> equals M275 EV -> FAIL
Step 4: Revert M14.json -> test PASSES
```
This confirms the differential assertion is not trivially true — it catches the real isolation property.

**Manifest dependency risk** (Q7 from proposal §11): Tests using `compute_effective_version_for_machine("M14", 1)` dynamically depend on `slot_designer/configs/machine_manifests/M14.json` being present. If CI excludes manifest files, tests fail with `FileNotFoundError`. This is documented but not a design blocker.

**Verdict: pass**

---

## §3 Cases That Break

Two breaks were found by active search — not caught by the proposal's §7 regression risk analysis.

### Break B1: `test_c6_gap_3_pid_666_trigger_marker.py:160` — missed in proposal §7

**Root cause**: The proposal's §7 states:

> `test_c6_gap_3_pid_666_trigger_marker.py` — asserts `"data_inferred"` for M275. If M275's `scatter_feature_names` has 2 features, the d3 "unique" branch does NOT fire for M275 — M275 still gets `"data_inferred"`. **No change needed for this test.**

The proposal focused on the `trigger_target_confidence` (`data_inferred`) and concluded correctly that it doesn't change. But it missed that the same test also asserts the specific `trigger_target` VALUE at line 160:

```python
# tests/analyzer/test_c6_gap_3_pid_666_trigger_marker.py
class TestM275ScatterTriggerMarker:
    def test_pid_666_trigger_target_is_new_freespin(self, m275_row_by_pid):
        """pid 666 notes.trigger_target must be 'NewFreespin'."""
        notes = m275_row_by_pid["666"].get("notes", {})
        assert notes.get("trigger_target") == "NewFreespin", ...  # LINE 160
```

After D-2: `trigger_target` becomes `"NormalCollectionSpin"` → this assertion fails.

**Confirmed by running**: `pytest tests/analyzer/test_c6_gap_3_pid_666_trigger_marker.py` — currently 10 passed. Line 160 will turn RED after d2.

**Severity**: Blocking. CI breaks between D commit and the test fix.

**Required fix (for designer, not a redesign)**: Add `test_c6_gap_3_pid_666_trigger_marker.py` line 160 to the required-update list in proposal §7. The assertion must change from `== "NewFreespin"` to `== "NormalCollectionSpin"`. The test name `test_pid_666_trigger_target_is_new_freespin` should also be renamed to `test_pid_666_trigger_target_is_normal_collection_spin`.

---

### Break B2: `test_c6_bonus_chain_dynamics_plugin.py:432` — stash extension fixture gap

**Root cause**: After D-2, the plugin's `emit()` reads `stash.get("scatter_feature_chain_counts") or {}`. The existing unit test at line 414–435 builds a stash WITHOUT this new key, and with an UNSORTED feature names list:

```python
# Current fixture in test_c6_bonus_chain_dynamics_plugin.py (lines 416-419)
stash = {
    "bonus_chain_dynamics": {"applicable": True, "chain_count": 100},
    "scatter_feature_names": ["ZFeature", "AFeature"],  # unsorted (Z before A)
    # missing: "scatter_feature_chain_counts"            # will be {} after d2
}
```

After D-2, emit() logic:
1. `len(scatter_feature_names) == 2` → else branch (d2 path)
2. `_chain_counts = stash.get("scatter_feature_chain_counts") or {} = {}`
3. `max(["ZFeature", "AFeature"], key=lambda f: {}.get(f, 0))`
4. Both count=0 → `max()` returns `"ZFeature"` (first in list, leftmost tied value)

Test assertion at line 432: `assert row_666["notes"]["trigger_target"] == "AFeature"` → **FAIL**.

**Root of the failure**: The REAL PIA stash writes `scatter_feature_names = sorted(feat for feat in all_chains_by_feature.items() if afb.get("lengths"))` — a sorted list. From a sorted list `["AFeature","ZFeature"]`, `max()` with tied-zero counts returns `"AFeature"` (first in sorted list). But the test fixture skips the sort step and uses `["ZFeature","AFeature"]` — so `max()` returns `"ZFeature"`. The test was accidentally correct under the alphabetical-sort behavior (where `sorted(["ZFeature","AFeature"])[0] = "AFeature"`) and breaks when the code switches to chain-count max.

**Confirmed by Python simulation**:
```python
max(["ZFeature","AFeature"], key=lambda f: {}.get(f, 0))  # -> "ZFeature" (fails assert "AFeature")
```

**Severity**: Blocking. The test fixture is fragile and will produce a misleading failure message.

**Required fix (for designer, not a redesign)**: The proposal §7 says `test_c6_bonus_chain_dynamics_plugin.py` must be updated. The designer must specify:
1. The fixture stash must add `"scatter_feature_chain_counts": {"AFeature": 100, "ZFeature": 1}` (making AFeature win by count)
2. The test must assert `trigger_target == "AFeature"` with a new explanation: "AFeature has higher chain count (100 > 1)"
3. The scatter_feature_names list should be sorted in the fixture (matching PIA behavior): `["AFeature","ZFeature"]`

---

## §4 Hash Composition Trace

For each case: "if I change file X, does this case's effective_version change?"

### File X = `payouts_by_spin_type.py` (D-1 fix)

The `PayoutsBySpinType` plugin is declared by ALL 253 non-variant machines. Changing any byte of this file flips `PayoutsBySpinType.compute_hash()`.

| Machine | EV changes? | Old EV | New EV |
|---|---|---|---|
| M275 | YES | `5c78f3834a1e` | `<NEW_M275_EV>` |
| M272 | YES | `6aae41144cea` | `<NEW_NON_M275_EV>` |
| M14  | YES | `6aae41144cea` | `<NEW_NON_M275_EV>` |
| M37  | YES | `6aae41144cea` | `<NEW_NON_M275_EV>` |
| M11  | YES | `6aae41144cea` | `<NEW_NON_M275_EV>` |
| Hyp 50-payline | YES | (any) | (new) |
| Hyp single-scatter | YES | (any) | (new) |

**Isolation property**: M275 EV still differs from M14/M37/M272 EVs after D-1 (M275 has `multiplier_wild`, the others do not — this plugin's hash is unchanged by the paylines fix). The structural property `m275_ev != m14_ev` is preserved.

**Symmetry property**: M14/M37/M272 all have the SAME 8-plugin set. Their EVs are XOR/hash compositions of the same input → same output. `m14_ev == m37_ev == m272_ev` still holds after D-1.

**base_hash**: UNCHANGED. `payouts_by_spin_type.py` is in `features/`, not `core/`. `fa440e3eb5f6` remains valid.

**Pin assertions (pre-E)**: FAIL. `"6aae41144cea"` is wrong for M14 (3 pin sites). `"5c78f3834a1e"` is wrong for M275 (1 pin site).

**Differential assertions (post-E)**: PASS. Both structural properties preserved.

### File X = `bonus_chain_dynamics.py` (D-2+D-3 fix)

The `BonusChainDynamics` plugin was added to all 253 non-variant machines in C6. Changing any byte flips `BonusChainDynamics.compute_hash()`.

**Same blast radius as D-1**: All 253 machines get new EVs. M275's EV flips from its current value (incorporating the new bonus_chain_dynamics hash). Non-M275 machines' EVs flip from their current value.

**If D-1 and D-2+D-3 in same Cluster D commit**: The two plugin hash changes are XORed into the final EV. Each plugin's hash contributes once. The EV flip happens once at commit time, not twice. This is the correct behavior and matches the proposal's design.

### File X = `player_impact_analyzer.py` (D-4 inline, Cluster A control flow)

PIA is NOT a plugin file. `compute_effective_version_for_machine()` does NOT hash PIA bytes.

| Machine | effective_analyzer_version changes? | analyzer_version (legacy) changes? |
|---|---|---|
| M275 | NO | YES (all 393 machines) |
| M14  | NO | YES |
| All 393 | NO | YES |

**The D-4 blast radius is minimal**: Only the legacy `analyzer_version` string flips, not the per-plugin `effective_analyzer_version`. This is the lower blast radius option (proposal §5.4 recommendation: fix in PIA inline, not in collect_mechanic.py).

**Cluster A blast radius**: Same as D-4. PIA control-flow change → `analyzer_version` flips → `effective_analyzer_version` unchanged. No test using `effective_analyzer_version` pins is affected.

### Summary table

| What changes | effective_analyzer_version flips? | base_hash changes? | Cluster E pins survive? |
|---|---|---|---|
| payouts_by_spin_type.py (D-1) | YES — 253 machines | NO | YES (differential assertions) |
| bonus_chain_dynamics.py (D-2+D-3) | YES — 253 machines | NO | YES (differential assertions) |
| player_impact_analyzer.py (D-4, A) | NO | NO | YES (unaffected) |
| core/*.py (hypothetical, out of scope) | YES — all machines | YES | NO (base_hash pin would catch it) |
| tests/*.py (Cluster E) | NO | NO | N/A (test-only) |

---

## §5 Backward-Compat Check

### Cluster E (test-only, full backward-compat)

No code files changed. All 393 machines' `effective_analyzer_version` values are unchanged. All existing reports serve with identical content. All existing API responses return identical data. Full backward-compat.

### Cluster D fixes — per-fix analysis

**d1 paylines sort (32 machines affected)**:
- Existing on-disk summaries: paylines arrays are misordered for 32 machines. Content is readable; no consumer crashes.
- After D-1 deploy: all 253 machines' EVs flip → UI shows "historical" badge → signals regeneration needed.
- No consumer code reads `paylines` for routing decisions — all consumers are display-only.
- Regen required for: 32 Ax4-B machines to get correct display order.
- Frontend impact: misordered payline rows in panel display for 32 machines until regen.

**d2 trigger_target (~37 machines affected)**:
- Existing on-disk summaries: `trigger_target = "NewFreespin"` (wrong) for ~37 machines.
- After D-2 deploy: all 253 machines' EVs flip → same historical badge signal.
- No frontend renderer for `trigger_target` currently (03 §3 Symbol D-2: 0 frontend consumers).
- Regen required for: ~37 Ax7-C scatter machines to get `"NormalCollectionSpin"`.

**d3 unique confidence (0 current machines)**:
- No existing summary is affected. The "unique" branch is dead code.
- Full backward-compat. No regen needed.

**d4 avg_bonus_payout (edge-case BCM machines)**:
- Frontend already null-safe (`app.js:6196 != null` guard).
- Existing reports with `avg_bonus_payout = 0.0` for the edge case: display `"0"` before regen, `"—"` after.
- No functional breakage. Display-only change.
- No regen required for correctness; cosmetic improvement after regen.

### Cluster A (error paths only)

Success-path reports: 100% unchanged. The try/finally adds behavior only on error paths that currently never fire in production (no cyclic plugins, no DECLARED_DEPS typos). All existing reports serve identically.

Error-path additive behavior: future runs that encounter topo errors will produce a `player_impact_summary.json` that previously did not exist. This is purely additive and does not affect existing reports.

**Overall backward-compat verdict**: Partial. Reports can be served without regen. For the 32+37 affected machines, reports display wrong data (wrong paylines order, wrong trigger_target value) until regen. No service disruption; no consumer crashes.

---

## §6 Verdict

### Overall verdict: APPROVE-WITH-REVISIONS

The proposal is architecturally sound. The phase ordering (E → D → A), the differential assertion approach, the chain-count majority vote, the int-sort fix, and the try/finally error pattern are all verified correct by running real code and reading real cached summaries.

**Two blocking test-update gaps found** (not design flaws — omissions in §7 regression risk documentation):

**Break B1** — `test_c6_gap_3_pid_666_trigger_marker.py:160`:
- Currently asserts `trigger_target == "NewFreespin"`
- After d2: `trigger_target` becomes `"NormalCollectionSpin"` → RED
- Proposal §7 says "no change needed" — incorrect
- Fix: add this test to the required-update list; change assertion to `== "NormalCollectionSpin"`

**Break B2** — `test_c6_bonus_chain_dynamics_plugin.py:432`:
- Fixture uses `["ZFeature","AFeature"]` (unsorted) with no `scatter_feature_chain_counts`
- After d2: `max()` over tied-zero-count list returns `"ZFeature"` (first in unsorted list)
- Assertion `== "AFeature"` fails
- Fix: add `scatter_feature_chain_counts` to fixture; sort the feature names list; update expected value

Neither break requires design revision. Both are in the implementation guidance section (§7), not in the architecture. The designer updates §7 and the impl team applies the corrections during Phase 2 (Cluster D).

### Per-case verdicts

| Case | Verdict | Notes |
|---|---|---|
| 1 — M275 | pass | d2 fix verified correct; B1 test gap surfaced |
| 2 — M272 | pass | chain-count heuristic generalizes to BCM_FREESPIN archetype |
| 3 — M14 | pass | all fixes inapplicable or no-change; isolation property confirmed |
| 4 — M37 | pass | all fixes inapplicable; empty paylines list handled correctly |
| 5 — M11 | pass | all fixes inapplicable; success-path Cluster A behavior confirmed |
| 6 — Hyp 50-payline | pass | d1 fix is correct; 32 machines need regen; new test required |
| 7 — Hyp single-scatter | pass | d3 fix is correct; 0 current fleet impact; new test required |
| 8 — Cluster E migration | pass | differential assertions verified non-trivial; inject-bug recipe works |

**6 pass / 0 partial / 0 broken** (breaks are in test documentation, not in design)

### Open questions from proposal §11 — validator assessment

**Q6 (write-order guarantee)**: Confirmed correct. `summary["analyzer_init_error"]` is set before `_safe_write_summary_json` is called, before `raise SystemExit(1)`. Single-threaded Python guarantees ordering. No race condition possible.

**Q7 (CI manifest dependency)**: Risk is real and present with the current differential assertion approach. `compute_effective_version_for_machine("M14", 1)` reads `slot_designer/configs/machine_manifests/M14.json` at test runtime. A CI environment without manifest files would see `FileNotFoundError`. This is an accepted documented risk per proposal §3.4 (no shared conftest recommendation stands). Not a design blocker.

**Q8 (tie-breaking when chain counts equal)**: Ties resolve to the first element in the `sorted()` list from the PIA stash (alphabetically first). This is deterministic and documented. For current fleet machines (NCS=841 vs NF=67, NCS=554 vs NF=41), ties do not occur. The tie-break is acceptable for Round 1. Not a blocking concern.

**Additional finding (Q-validator-1, d2 tie-breaking in unit tests)**: The unit test fixture at line 414 uses unsorted `["ZFeature","AFeature"]`. After d2, this produces `"ZFeature"` (first in unsorted list) not `"AFeature"` (first in sorted list). This is different from the PIA behavior which always supplies a sorted list. The test fixture must match PIA's sorting behavior to test the right invariant. See Break B2.

---

*Validation complete. 8 cases walked. 612 tests confirmed passing pre-fix. Two test-update gaps (B1, B2) found in proposal §7 regression risk section. Design is architecturally correct. Required designer action: update §7 with the two missing test updates. No redesign needed.*
