# 05 — Architecture Critique: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Role**: arch-critic (W3)
> **Proposal reviewed**: `04_architecture_proposal.md`
> **Wave 1 evidence base**: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`
> **Verdict**: APPROVE-WITH-REVISIONS

---

## §1 Top Concerns (3-5 most serious)

**TC-1 — The gap_3 test hardcodes the WRONG value and will require update as part of D-2, but the proposal undercounts affected tests.**
`test_c6_gap_3_pid_666_trigger_marker.py:160` asserts `trigger_target == "NewFreespin"` — the current wrong behavior. The proposal §7 says "Only a value assertion (`== "NewFreespin"`) would fail, and such a value assertion (if it exists) must be updated as part of D-2." The qualifier "if it exists" is wrong — it does exist, and the test name literally documents the wrong behavior as the expected output (`test_pid_666_trigger_target_is_new_freespin`). The proposal also lists `test_c6_bonus_chain_dynamics_plugin.py` as the only test needing update (§7), but `test_c6_gap_3_pid_666_trigger_marker.py` is a second test that hardcodes the wrong value. There are two tests to update, not one.

**TC-2 — D-2 semantic mismatch: chain-count majority vote measures "which feature had more chains", not "which feature is directly triggered by the scatter pid".**
The BCD plugin docstring (lines 39-43) describes cases 2 and 3 of the inference: case 2 is "exactly one feature with chain data → `data_inferred`", case 3 is "multiple features → first alphabetically." The D-2 fix changes case 3 to "highest chain count." But the docstring's stated invariant for M275 is "by_feature has `NormalCollectionSpin` → trigger_target = `NormalCollectionSpin`" (line 47) — this was written assuming only one feature has data at M275. The taxonomy (02 §8) confirms M275 has TWO features with chain data: NCS=841, NewFreespin=67. The majority vote gives the right answer for M275 because 841 > 67. But the semantic basis is still wrong: a high chain count does not mean the scatter triggered that feature; it means more bonus sessions of that type were observed overall. A future machine where the *lower*-chain-count feature is the direct scatter trigger would silently get the wrong value again with the same "data_inferred" confidence. The proposal acknowledges this in §11 Q2 but does not resolve it.

**TC-3 — Cluster A adds a new `write_summary_json` call site on the error path, but the DECLARED_DEPS error fires INSIDE the emit loop where some features have already emitted, producing a partial summary written to disk as if it were a partial-success. The proposal calls this "acceptable — `analyzer_init_error` key signals partial data" (§4.3), but no test validates that the partial on-disk JSON cannot be silently consumed as a complete one.**
Per 03 §6.1 mitigation note: "A new test would need to spawn a PIA subprocess with an injected cyclic plugin and assert that the on-disk JSON contains `analyzer_init_error`." The new test specified in §4.4 only tests the topo-sort path (Region 1). Region 2 (DECLARED_DEPS inside emit loop) has no test specified, even though it has an additional structural risk — partial plugin output preceding the error key.

**TC-4 — Phase order `E → D → A` has a gap: if the Cluster E differential assertions are wrong (e.g., the structural assertion is trivially true), the CI will not turn RED from D, and the flaw will pass undetected until someone manually checks. The inject-bug recipe for Cluster E (§7) depends on modifying a manifest, which is an out-of-band change not part of the CI test suite.**

**TC-5 — The `PluginDeclaredDepMissingError` proposal introduces a new exception class that is semantically nearly identical to the existing `PluginMissingDependencyError`, but catches a structurally different thing: REQUIRES-time missing dep (caught by topo_sort during sort) vs. runtime-summary-key missing dep (caught during emit loop). The proposal recommends A-3b (new class) in §4.3 but then explicitly raises this as Q4 in §11 for Wave 3. The distinction is real (REQUIRES is a plugin-graph concept; DECLARED_DEPS is a summary-key concept) but both are "a declared dependency is absent." If the two classes become indistinguishable to operators reading the JSON `error_type` field, the classification adds noise without diagnostic value.**

---

## §2 Required Fixes Before Approval

1. **Fix TC-1**: Proposal §7 (D-2 regression risk) must enumerate `test_c6_gap_3_pid_666_trigger_marker.py:160` as a required update alongside `test_c6_bonus_chain_dynamics_plugin.py`. Two test updates, not one. Implementer brief must name both.

2. **Fix TC-3**: Proposal §4.4 must add a Region 2 test: inject a DECLARED_DEPS failure (not just a topo-sort failure), assert that (a) rc=1 fires, (b) JSON is written to disk, (c) JSON contains `analyzer_init_error`, AND (d) the partial-plugin-output fields before the failing feature are present (documenting and validating the partial-state semantics).

3. **Clarify TC-5**: Proposal §4.3 must explicitly state which `error_type` string an operator sees in the JSON and why the two classes are distinguishable in operator workflow. If the diagnostic value is "different class name in `error_type` field", state this; do not leave it as an open question for Wave 3.

4. **Acknowledge TC-4 inject-bug gap**: The Cluster E inject-bug recipe (§7, "temporarily add multiplier_wild to M14's manifest") is not automatable in CI. The proposal should either (a) add a second inject-bug path that doesn't require manifest editing, or (b) explicitly accept this as a known CI gap.

---

## §3 Stress Questions

---

### Q1 — Phase order `E → D → A`: could `A → D` be safer?

**Question**: The coupling auditor (03 §6.1) says E must precede D. But A includes the `try/finally` around `write_summary_json`. What if D fixes accidentally trigger a write path that the new try/finally is meant to catch? Could `A → D` be a safer sequence for the write-path coverage?

**Designer's likely answer**: Cluster A wraps the error paths (lines 5044-5065, 5073-5080); the D fixes are in plugin `emit()` logic (payouts_by_spin_type, bonus_chain_dynamics) and the PIA inline stash (avg_bonus_payout at line 4817). The D fixes cannot trigger a topo-sort or DECLARED_DEPS error — they are inside the emit loop, which is already past those error paths. So `A → D` order has no advantage for error-path coverage.

**Why this is insufficient**: The question is specifically about the emit loop itself. D-4 modifies `player_impact_analyzer.py` (the inline stash block at `pia:4817`). Cluster A also modifies `player_impact_analyzer.py` (the error-handling blocks at `pia:5044-5080`). Both touch the same file. If A commits first, the impl team must merge A and D-4 changes to the same file without conflict. If D commits first, A's try/finally code has a clean base. The proposal claims A is independent of D and E for "control-flow purposes" (§2) and only defers A to "reduce CI broken windows" — but D-4 and A both touch `player_impact_analyzer.py`, making the merge sequence a real risk.

**Verdict**: PARTIAL. The control-flow argument is correct; the merge-conflict risk from two clusters touching the same file in the same commit sequence is not addressed.

---

### Q2 — Cluster A "two regions": what exactly IS region 2, and can a partial-success summary cause silent misuse?

**Question**: Region 2 (DECLARED_DEPS) fires inside the emit loop (`for _feature in _sorted_features:`). Some features may have already emitted. The JSON written to disk contains partial plugin output. Is a malformed (partial) summary distinguishable from a complete one by an operator?

**Designer's answer** (§4.3 control flow note): "This is acceptable — the `analyzer_init_error` key signals partial data."

**Why this is insufficient**: The backend at `_batch_gen_worker.py:154` returns `rc=1` and the worker short-circuits, so the partial summary never enters the normal report-reading path. But:

- The backend check at line 160 is `if not summary_file.exists()` — after the A-fix, the file WILL exist even on rc=1. The `if rc != 0: return` at line 154 runs first, so line 160 is never reached. Good.
- But the partial JSON is on disk and readable by a human operator. The `analyzer_init_error` key is present, but so are the successfully-emitted plugin keys. An operator who grepped for `payouts_by_spin_type` in the JSON would find valid-looking data from a run that failed mid-way. The proposal does not specify that partial-state keys should be marked or suppressed.
- The 14 test sites that assert `"analyzer_init_error" not in summary` on SUCCESS PATH only validate the success path. No test verifies that a DECLARED_DEPS error summary has the correct combination of partial keys + error key.

**Verdict**: PARTIAL (addresses backend consumption; does not address operator misinterpretation of partial JSON).

---

### Q3 — D-2 chain-count majority vote: does pid 666 semantically trigger NormalCollectionSpin, or is the chain-count signal a proxy with no game-logic grounding?

**Question**: Per the BCD plugin docstring (bonus_chain_dynamics.py:47): "For M275: by_feature has `NormalCollectionSpin` → trigger_target = `NormalCollectionSpin`." This docstring was written before C6 confirmed two features exist. The taxonomy (02 §8) shows M275 has NCS=841 chains and NewFreespin=67 chains. Which feature does pid 666 ACTUALLY trigger per game logic?

**Designer's answer** (§5.2): "The scatter trigger (pid 666) directly initiates [NormalCollectionSpin]... This is the most principled but requires the most stash extension."

**Why this is insufficient**: The proposal asserts NormalCollectionSpin is correct but cites only chain-count data as evidence. The BCD plugin docstring's case 2 ("exactly one feature") was the intended semantics when the docstring was written, but M275 actually has two features. The BCD plugin docstring line 47 says "For M275: by_feature has `NormalCollectionSpin` → trigger_target = `NormalCollectionSpin`" — but this was written when the codebase expected only one feature to have chain data. The 841 vs 67 count is consistent with NCS being the primary target, but the mechanism by which pid 666 triggers NCS vs NewFreespin is game-engine level, not chain-count level.

Per 02 §8 spot-check: only M275 and M272 were confirmed. For the ~37 affected machines, the proposal cannot prove the majority-chain-count feature is always the scatter trigger. It is a better heuristic than alphabetical, but it remains a heuristic.

**Verdict**: PARTIAL (heuristic is better than alphabetical, but "correct" is overstated; applicable to ~37 machines but validated on only 2).

---

### Q4 — D-1 `int()` carve-out: what happens for non-integer payline_id strings?

**Question**: The proposal says `int(x["payline_id"])` raises `ValueError` for non-numeric strings and cites `feedback_capture_drift.md` as justification for failing loudly. But the coupling audit (03 §6.2) flags this as a "silent type assumption." The proposal's defensive alternative (§5.1) is to use `isdigit()` + fallback, but the recommendation is the simple `int()` version. What specifically would a `ValueError` look like to the operator?

**Designer's answer** (§5.1): "A `ValueError` on a non-numeric payline_id is an EARLY SIGNAL of a schema drift... A try/except that converts `ValueError` into a `ValueError` raised with a descriptive message is the correct pattern if the implementer wants an informative error."

**Why this is insufficient**: The emit() call at `pia:5082` is wrapped in:
```python
try:
    _feature.emit(..., summary, _c1_ctx)
except Exception as _emit_exc:
    summary["feature_errors"][_feature.FEATURE_ID] = str(_emit_exc)
```
A `ValueError` from `int(x["payline_id"])` inside `payouts_by_spin_type.emit()` would be caught by this handler and silently recorded as `"feature_errors": {"payouts_by_spin_type": "invalid literal for int() with base 10: 'any'"}`. The run would continue with rc=0, and the operator would see a partial summary without a paylines section. This is not loud failure — it is exactly the silent-wrong-result mode that `feedback_capture_drift.md` warns against. The proposal's "early signal" claim assumes the `ValueError` propagates out of the plugin, but the emit-error handler catches it.

**Verdict**: NOT ADDRESSED. The proposal assumes ValueError propagates; it doesn't. The emit-error catch at pia:5083 swallows it into feature_errors. The implementer must add explicit pre-validation inside emit() or convert the ValueError to a more descriptive one before the emit-error handler catches it.

---

### Q5 — Cluster E structural differential: how is "M275 differs from M14 by exactly multiplier_wild contribution" asserted?

**Question**: The proposal's structural assertion for M275 is `m275_ev != m14_ev`. This is a necessary condition but not sufficient to assert "differs by exactly multiplier_wild contribution." What if M275 gained two new plugins accidentally? The assertion would still pass.

**Designer's answer** (§3.3): The assertions verify: (1) `m275_ev != m14_ev` (isolation), (2) `m14_ev == m37_ev == m272_ev` (symmetry), (3) format checks (12-char lowercase hex).

**Why this is insufficient**: The original pinned value asserted "M275 effective_version = 5c78f3834a1e" — catching the case where M275's plugins changed. After migration, the assertion only catches "M275 is different from M14" — it does NOT catch the case where M275 accidentally gained a plugin (it would be even more different from M14, but still pass `!=`). It also does NOT catch the case where M14 accidentally gained a plugin (both would shift, `!=` still passes, `==` among M14/M37/M272 would fail — this one is caught). The "canary against accidental plugin file modification" property is partially preserved (by the byte-identical tests per §3.2 "Cons" acknowledgment) but not fully by the differential assertion alone.

The coupling audit (03 §4 E-2) explicitly names this trade-off: "loses the ability to detect an unexpected hash change." The proposal says byte-identical tests provide this guard, but those tests only cover the 4 specifically tested machines (M14/M37/M272/M275) in their test-fixture mode. The differential assertion is a weaker guard, and the proposal's acknowledgment is adequate — but the claim "never needs updating; tests the real invariants" is incomplete.

**Verdict**: PARTIAL (acknowledged trade-off; the claim "tests the real invariants" is slightly overstated because the real invariant includes "exactly 1 plugin difference", not just "some difference").

---

### Q6 — `PluginDeclaredDepMissingError` vs. `PluginMissingDependencyError`: is a new class needed?

**Question**: `PluginMissingDependencyError` (topo_sort.py:63) is defined for "a plugin's REQUIRES lists a FEATURE_ID absent from the feature set." The DECLARED_DEPS check is "a plugin declares a SUMMARY KEY absent from the summary dict." These are different kinds of missing dep. But both appear in the `error_type` field of `summary["analyzer_init_error"]`. The proposal asks the critic to assess whether the new class is right.

**Actual code check**: `topo_sort.py:63-83` defines `PluginMissingDependencyError` with attributes `plugin` (FEATURE_ID of declaring plugin) and `missing_dep` (FEATURE_ID that was required). The DECLARED_DEPS check is about a SUMMARY KEY (e.g., `"collect_mechanic.bonus_cycle_correction"`), not a FEATURE_ID. The error messages would be semantically different: "plugin requires feature X not in the feature set" vs. "plugin requires summary key Y not in the summary dict." Using the same class for both would conflate plugin-graph resolution errors with runtime-state errors.

**Designer's position** (§4.3 A-3b): new class is cleaner; "different kind of missing dependency."

**Assessment**: The semantic distinction is real and the new class is justified. The existing `PluginMissingDependencyError.__init__` takes `missing_dep: str` (a FEATURE_ID), which would be misleading if reused for a summary key. The new `PluginDeclaredDepMissingError` class should take `plugin: str` and `missing_dep_key: str` (the summary key), making the distinction obvious. The proposal's recommendation is sound.

However: the proposal adds the new class to `topo_sort.py` (§9 Phase 3 deliverables), but the new error is conceptually not a topo-sort error — it's an emit-loop runtime error. Putting it in `topo_sort.py` creates a semantic coupling: `topo_sort.py` becomes "plugin dependency resolution errors" (its current scope) AND "runtime summary-key dependency errors" (the new scope). A better home might be a new file or `pipeline_context.py`.

**Verdict**: PARTIAL (new class is justified; file placement in topo_sort.py creates semantic scope creep).

---

### Q7 — D-4 `avg_bonus_payout None` fix location: is PIA inline the stable long-term home?

**Question**: The proposal fixes `avg_bonus_payout` in the PIA inline block (`pia:4817`) rather than in `collect_mechanic.py`. This keeps plugin files clean but means the fix lives in the giant `player_impact_analyzer.py` rather than the owning plugin. Per §11 Q1, the designer explicitly asks about this.

**Analysis**: Per 01 §3.4 "Note: this change is in the PIA inline stash-writing block at pia:4817, which is pre-emit code... no change needed to collect_mechanic.py itself." Per 02 §6: "the stash's `avg_bonus_payout` is for display only in the summary panel." The computation at `parser.py:321-323` (`_compute_bonus_correction`) recomputes its own average independently, so the PIA inline value is purely display.

The concern is future Cluster C (F6 cleanup + Registry build position refactor, §10 deferrals): "The F6 inline block in PIA duplicates logic now owned by the BCD plugin. Cleaning it up requires verifying the invariant assert... a separate arch round." The `avg_bonus_payout` computation is in the same F9-adjacent inline block (the `_collect_mechanic_data` stash, not F6 which is `_bonus_chain_dynamics_data`). When Cluster C moves F6 into the plugin, the `avg_bonus_payout` computation may not move with it (it's a different stash block). The PIA inline fix is stable for this round, but creates technical debt for Cluster C.

**Verdict**: PARTIAL (stable for Round 1; creates tech debt flagged for Cluster C; proposal correctly defers this to Cluster C).

---

### Q8 — Commit grouping: 3 commits through impl-* loop is 3× overhead. Is the trade-off analysis complete?

**Question**: 3 commits = 3 × (implementer + tester + verifier + critic + committer). That's 15 sub-agent invocations vs. 5 for a single mega-commit. Is the overhead justified?

**Designer's answer** (§6): "Ordering constraint from 03 §8 fragility hotspot rank 5 is explicit — E must commit BEFORE D... With 3 separate commits, each commit is reviewable independently, CI passes at each step."

**What the proposal omits**: The `feedback_impl_team_required.md` memory says "impl-* 4-agent team for cross-cutting refactor." Each cluster requires one full impl-* loop per the memory constraint. The proposal's commit structure maps 1:1 to impl-* loops (3 clusters = 3 loops). This is the correct application of the memory constraint, not an overhead choice. The alternative (1 mega-commit) would violate the E-before-D ordering within a single impl-* loop — the implementer would have to order changes within the working tree, which is fragile.

The real question is: could E+D be a single commit with E changes committed atomically first in the same PR? In git terms: yes, a single commit can include E changes in the test files and D changes in the plugin files, ordered by file. But the impl-* team's verifier would need to run the full suite at an intermediate state (after E files applied but before D files applied) — impossible within a single commit. The 3-commit structure is operationally correct.

**Verdict**: ADEQUATELY ADDRESSED (the overhead is real but correctly derived from memory constraints; the trade-off analysis is complete enough).

---

### Q9 — D-2 fallback when `scatter_feature_chain_counts` is missing or empty: "falls back to alphabetical" is not a regression fix.

**Question**: Per §5.2: "Falls back to alphabetical sort if counts are tied or missing." The code sketch uses `stash.get("scatter_feature_chain_counts") or {}`. If the stash extension (new `scatter_feature_chain_counts` key in F6 inline) is not deployed (e.g., rollback of D-2 partial commit), the fallback returns alphabetical — the same wrong behavior as before D-2. Is this fallback the right design?

**Designer's answer** (§5.2): "if `max()` would be ambiguous (two features with identical chain counts), the tie is broken by alphabetical sort (same as current behavior)."

**Why this is problematic**: The fallback to alphabetical applies in two distinct cases that the proposal conflates:
1. Chain counts are genuinely equal (rare, tie-break acceptable).
2. `_chain_counts` dict is empty or missing (stash extension wasn't written). In case 2, `_chain_counts.get(f, 0)` returns 0 for all features, and `max()` on a list of zeros falls back to the first element returned by `max()` — which for a dict/list is implementation-defined in Python when all keys have equal values. Python's `max()` returns the first maximum found, which for a list is the first element — which happens to be the first element of `scatter_feature_names`. Since `scatter_feature_names` is built as `sorted(...)` in the stash (line 4864: `"scatter_feature_names": sorted(...)`), the fallback actually IS alphabetical sort, same as before. So a missing `scatter_feature_chain_counts` key silently reverts to the current wrong behavior with no error.

Per `feedback_capture_drift.md` and `feedback_no_silent_swallow.md`: a missing stash key that silently degrades to wrong behavior is exactly the pattern those memories forbid. The plugin should raise a RuntimeError (caught as `feature_errors`) if `scatter_feature_chain_counts` is absent when `scatter_feature_names` is non-empty.

**Verdict**: NOT ADDRESSED. The silent fallback to alphabetical on missing stash key is wrong. Should raise RuntimeError for missing `scatter_feature_chain_counts` when `scatter_feature_names` is non-empty.

---

### Q10 — Backend reader of `summary["analyzer_init_error"]` after A-fix: does any backend file read it?

**Question**: Per §10 deferrals: "Currently 0 production code reads this field... The field written to disk by Cluster A is for operator manual inspection only." The coupling audit (03 §2 Symbol A-1) confirms 0 production readers. But the `_batch_gen_worker.py` check at line 154 is `if rc != 0` — the backend already has the error signal. After the A-fix, the JSON is also on disk. What prevents a future operator from manually grepping for the field and misreading a partial-success (DECLARED_DEPS) summary as a complete run?

**What the code actually shows** (verified at `_batch_gen_worker.py:154-160`):
- Line 154: `if rc != 0: return {"ok": False, "error": f"analyzer rc={rc}"}` — short-circuit before line 160.
- Line 160: `if not summary_file.exists(): return {..}` — only reached if `rc == 0`.
- After the A-fix, `summary_file` EXISTS even when `rc != 0`, but line 160 is never reached on error.

The proposed backend fix (§10 deferrals): "Backend surface for `analyzer_init_error`: Currently 0 production code reads this field. The field written to disk by Cluster A is for operator manual inspection only."

**Assessment**: No backend consumer exists. The 0-consumer claim is verified by grep. The proposal correctly defers UI surfacing to Cluster G. The risk is purely operator-side misinterpretation, which the proposal acknowledges.

**Verdict**: ADEQUATELY ADDRESSED (0 backend consumers confirmed; risk is acknowledged; Cluster G deferred correctly).

---

### Q11 — Test file enumeration for Cluster E: the proposal specifies 2 files for migration, but are all affected files identified?

**Question**: The proposal says 2 files migrate (test_c3_5_isolation_m275_only.py, test_c3_5_m14_no_multiplier_wild.py). The W1 mapper enumerated 8 files with hex patterns (01 §4.1). Are all 8 correctly classified as "no change" or "migrate"?

**Exact per-file check against 01 §4.1 and 03 §4 E-2**:

| File | Hex | Change in D? | Proposal action | Correct? |
|---|---|---|---|---|
| test_c3_5_isolation_m275_only.py | M275 ev (5c78f3834a1e) + non-M275 ev (6aae41144cea) + base_hash | Yes (D-1 and D-2+D-3) | MIGRATE ev pins, KEEP base_hash | Correct |
| test_c3_5_m14_no_multiplier_wild.py | non-M275 ev (6aae41144cea) | Yes | MIGRATE | Correct |
| test_c3_base_hash_flips_for_round_level_enrichment.py | C2 base_hash + C3 base_hash | No (core unchanged) | NO CHANGE | Correct |
| test_c3_5_m275_e2e.py | hex in DOCSTRING only | No | NO CHANGE | Correct |
| test_c6_carve_completion.py | base_hash | No | NO CHANGE | Correct |
| test_c6_byte_identical_bonus_chain.py | base_hash | No | NO CHANGE | Correct |
| test_c5_byte_identical_unrelated_fields.py | base_hash | No | NO CHANGE | Correct |
| test_c1_byte_identical_m14.py | hex in COMMENT only | No | NO CHANGE | Correct |

All 8 files are correctly classified. The proposal's enumeration is complete.

However: the proposal says "5–8 files" in 01 §1 Cluster E row and "5 test files" in the brief §2 Cluster E scope. The actual count of files requiring migration is 2 (not 5 or 5-8). This discrepancy between the brief's scope and the proposal's migration plan is not highlighted. The implementer may expect 5 files and spend time on files that need no change.

**Verdict**: ADEQUATELY ADDRESSED for migration correctness; minor scope-description inconsistency (brief says "5+ files", proposal migrates 2, reason is that the other 3 base_hash pins don't need migration — this should be stated more explicitly in the Phase 1 deliverables).

---

### Q12 — D-2 + D-3 same-file commit: is D-3 actually testable when 0 fleet machines trigger the "unique" branch?

**Question**: D-3 fires when `len(scatter_feature_names) == 1`. Taxonomy (02 §3 Ax7-B) confirms 0 current fleet machines have exactly 1 active feature. How is D-3 tested on real fleet data?

**Designer's answer** (§5.3): "A new unit test asserting that when a mock stash has exactly 1 entry in `scatter_feature_names`, the emitted `trigger_target_confidence == "unique"`. Inject-bug recipe: remove the `len == 1` branch → fixture with 1 feature still emits `"data_inferred"` → test RED."

**Assessment**: Unit tests with mock stash are sufficient here. The test does not depend on real fleet data — it injects a controlled stash with 1 feature. This is consistent with how the existing BCD plugin tests are structured (test_c6_bonus_chain_dynamics_plugin.py uses mock stash objects throughout). The inject-bug recipe is automatable. No fleet-data dependency exists for D-3.

The risk is that D-3 ships with correct unit test coverage but is NEVER triggered in production until a new machine type is onboarded. If D-3 is later broken by a future change (e.g., someone changes `scatter_feature_names` construction to always include a sentinel entry), the unit test catches it. This is the correct outcome for a dead-branch fix.

**Verdict**: ADEQUATELY ADDRESSED (unit test with mock stash is the right testing strategy; no fleet validation possible for dead branch).

---

## §4 Migration Risk Inventory

### Phase 1 (Cluster E) Risks

**E-R1 — Differential assertions lose the per-machine hash snapshot property.**
After Cluster E, if someone accidentally adds a plugin to M275's manifest or modifies a plugin file, the test `m275_ev != m14_ev` still passes (M275 is still different from M14). The byte-identical tests (test_c5_byte_identical_unrelated_fields, test_c6_byte_identical_bonus_chain) provide some guard, but only for the specific fixture-machine reports they cover.

**E-R2 — `compute_effective_version_for_machine` at test runtime introduces manifest dependency.**
Per 03 §6.4: tests that call this function dynamically fail with `FileNotFoundError` if manifests are absent. In a partial checkout or CI that excludes `slot_designer/configs/machine_manifests/`, ALL differential tests fail for an unrelated reason. The proposal acknowledges this (§3.4) but does not propose a mitigation (e.g., fixture manifests in the test directory).

**E-R3 — Rollback of Cluster E re-introduces RED tests immediately when D is committed.**
If Cluster E is rolled back (test regression caused by incorrect differential assertions), the hardcoded constants return. Any subsequent D-commit immediately turns those tests RED. Rollback of E without rollback of D is not a stable state.

### Phase 2 (Cluster D) Risks

**D-R1 — 253-machine effective_analyzer_version invalidation.**
After D-1 (payouts_by_spin_type.py change) and D-2+D-3 (bonus_chain_dynamics.py change), all 253 machines' on-disk reports become "historical" in the UI. Reports are not deleted (md5-is-a-tag invariant), but operators who use `effective_analyzer_version` as a freshness signal will see all reports stale. Concurrent session rawdata (in-flight runs) will produce summaries with the new `effective_analyzer_version`. If an operator is comparing reports across a migration window, they may compare a pre-D report (old version) with a post-D report (new version) without realizing.

**D-R2 — Two tests hardcode the WRONG behavior for `trigger_target`.**
`test_c6_gap_3_pid_666_trigger_marker.py:160` asserts `"NewFreespin"` — the wrong value. `test_c6_bonus_chain_dynamics_plugin.py:432` asserts `"AFeature"` (alphabetically first) in a mock with 2 features. After D-2, the alphabetically-first behavior changes to chain-count-first. Both tests will turn RED. The proposal mentions only one of these (§7 mentions "The existing test `test_c6_bonus_chain_dynamics_plugin.py` asserts `trigger_target == "NewFreespin"` for M275" — but this is wrong; that test uses a mock with "AFeature"/"ZFeature", not the M275 fixture). The GAP #3 test (`test_c6_gap_3_pid_666_trigger_marker.py:160`) asserts the actual M275 cached fixture value "NewFreespin", and the proposal §7 only partially covers it.

**D-R3 — D-4 in PIA inline touches `player_impact_analyzer.py` which is also touched by Cluster A.**
When impl team commits D and A in sequence, two independent changes to the same file must be applied. If D is committed first, A must rebase/merge cleanly. If A is committed first (not the proposed order), D must merge cleanly. The proposal's recommended order (E → D → A) means D modifies `player_impact_analyzer.py` at line 4817 and A modifies it at lines 5044-5080. These are non-overlapping code regions, so mechanical merge conflict is unlikely, but the impl team must validate no interference.

**D-R4 — `scatter_feature_chain_counts` stash key added by D-2 but not validated for presence in BCD plugin.**
The proposal's D-2 code sketch uses `stash.get("scatter_feature_chain_counts") or {}`. If the PIA inline stash extension is implemented but has a key name mismatch (e.g., `scatter_chain_counts` instead of `scatter_feature_chain_counts`), the plugin silently falls back to alphabetical sort. No loud failure. Per `feedback_capture_drift.md`, the plugin should validate the stash key is present.

**D-R5 — D-1 triggers `ValueError` for non-integer payline_id strings, silently captured by emit-error handler.**
Per Q4 analysis: `int(x["payline_id"])` inside `emit()` raises `ValueError` on non-integer payline strings. The outer `try/except Exception` at `pia:5083` catches this and writes it to `summary["feature_errors"]["payouts_by_spin_type"]`. The run continues with rc=0 and no paylines section — a silent partial failure. This is a forward-looking risk for new machine types, but it violates `feedback_capture_drift.md` semantics.

### Phase 3 (Cluster A) Risks

**A-R1 — `_safe_write_summary_json` wrapper: if the wrapper itself has a bug, SystemExit may be swallowed.**
The `_safe_write_summary_json` sketch (§4.3) catches `Exception`. If `write_summary_json` raises `SystemExit` internally (unlikely but possible via a chain of calls), the catch clause misses it (Python doesn't catch `SystemExit` with `except Exception`). This is actually safe: `except Exception` does NOT catch `SystemExit` or `KeyboardInterrupt` in Python 3. The wrapper is correct as sketched.

**A-R2 — Partial summary written on DECLARED_DEPS error has no "partial" marker beyond `analyzer_init_error`.**
After some features have successfully emitted (their keys are in summary), the DECLARED_DEPS error fires and the summary is written to disk. The disk JSON contains real plugin data from pre-error features AND `analyzer_init_error`. An operator reading the JSON might trust the pre-error plugin data without noticing the error key. The proposal says "acceptable" — this is the primary unresolved operator-safety risk.

**A-R3 — The new test `test_a_init_error_disk_surfacing.py` covers Region 1 (topo-sort) but not Region 2 (DECLARED_DEPS) per §4.4 specification.**
The test spec only mentions "inject a cyclic plugin pair" (Region 1). Region 2 requires injecting a DECLARED_DEPS failure — a different injection mechanism. Two separate inject-bug recipes are needed; the proposal specifies only one.

**Rollback failure modes:**
- Cluster E rollback: safe (test-only), no production impact.
- Cluster D rollback: 253 machines' `effective_analyzer_version` reverts to pre-D value. On-disk reports from D-era become "historical" (stale badge) again. No data loss, no broken consumers. Clean rollback.
- Cluster A rollback: removes the try/finally error-writing. Any on-disk summaries written during the A-era (on error paths) become orphaned (backend can't find them since rc=1 was returned without the JSON). No consumer breaks since 0 production code reads `analyzer_init_error`.

---

## §5 Edge Cases Not Covered

**EC-1 — Machine with scatter marker AND `scatter_feature_names = []` but `scatter_feature_chain_counts = {}` in extended stash.**
Per taxonomy 02 §3 Ax7-A (M274): `by_feature = {}`, `scatter_feature_names = []`. The proposed stash extension adds `scatter_feature_chain_counts` built from the same filter: `{feat: len(afb["lengths"]) for feat, afb in all_chains_by_feature.items() if afb.get("lengths")}`. For M274, `all_chains_by_feature` is empty or all features have empty `lengths` — so both `scatter_feature_names` and `scatter_feature_chain_counts` are empty. The BCD emit code hits the `elif scatter_marker_pids:` branch (no `scatter_feature_names`) → `trigger_target = None, confidence = "unknown"`. M274 behavior is UNCHANGED by D-2 fix. This is correct but not explicitly stated in the proposal.

**EC-2 — New machine onboarded with `scatter_feature_names = ["OnlyFeature"]` after D-3 ships.**
The D-3 fix emits `"unique"` confidence for len==1. For a new machine with exactly 1 feature, `trigger_target = "OnlyFeature"`, `trigger_target_confidence = "unique"`. This is the intended behavior. The test for D-3 covers this case. However: `trigger_target_confidence = "unique"` in the output JSON has no frontend consumer (03 §3 Symbol D-3). When Cluster G (frontend) is implemented, the frontend must handle `"unique"` as a valid confidence value. The proposal notes this as Cluster G deferred work (§10), which is correct.

**EC-3 — The `_safe_write_summary_json` function is defined inline in PIA main() as a local function. On the DECLARED_DEPS path (Region 2), `_safe_write_summary_json` is called from inside the `for _feature in _sorted_features:` loop. After the call, `raise SystemExit(1) from _dep_exc` fires. The loop's iteration state is abandoned mid-loop. If Python's garbage collector does something unusual with the loop state (e.g., `_feature` is a plugin object with a `__del__` that modifies `summary`), the summary written to disk by `_safe_write_summary_json` may differ from the summary at the point of the call.**
This is a theoretical risk — no current plugin has `__del__`. But it is an edge case not discussed in the proposal.

**EC-4 — D-1 trigger-marker path (line 424): the `"-1"` special carve-out in Site 2 (line 431: `if pl_id != "-1"`) is NOT present in Site 1 (line 424: trigger-marker path). For the trigger-marker path, ALL payline entries including `"-1"` are included in the sort. With `key=lambda x: int(x["payline_id"])`, `"-1"` sorts as -1, which is before all positive payline IDs. This is the correct behavior. But the proposal's description says "the `-1` carve-out: int(-1) = -1 sorts before all positive integers naturally. No special-casing needed." This is correct for Site 1, where `-1` should be included. For Site 2, the `if pl_id != "-1"` carve-out ALREADY excludes `-1` before sorting, so the `int()` fix doesn't affect `-1` at all for Site 2. The proposal is accurate but the explanation implies the `-1` issue is symmetric across both sites, which it is not.**

**EC-5 — Two test files with the same constant name `_NON_M275_EFFECTIVE_VERSION`: after Cluster E migration, both files replace their constant with structural assertions. If a future developer adds a NEW hardcoded effective_version constant to EITHER file (e.g., during a new C-phase), the E-migration provides no protection against that new constant being stale. The E-migration fixes the existing constants but does not install a lint rule or architectural convention preventing re-introduction of hardcoded effective_version pins.**

**EC-6 — The proposal's Cluster A fix writes `summary["analyzer_init_error"]` and then calls `_safe_write_summary_json`. The JSON serialization of the summary at this point includes ALL keys set before the error — including `_`-prefixed temp keys that would normally be cleaned up at `pia:5115-5117` (which runs AFTER the emit loop, not before it). For the topo-sort path (Region 1, before emit), no `_`-prefixed temp keys from plugins exist yet (only `_bankruptcy_rows`, `_bankruptcy_sim_session_spins`, and `_bonus_chain_dynamics_data` from F6 inline). The on-disk summary on topo error will contain these `_`-prefixed temp stash keys as raw data. This is not handled by the cleanup at pia:5115 (since SystemExit fires before reaching that line). The proposal does not mention this.**

---

## §6 Hidden Assumptions

**HA-1 — All `bonus_chain_dynamics`-declaring machines have the same NCS+NewFreespin pattern.**
The proposal (§5.2, §11 Q2) assumes the NCS-majority pattern holds for "most" of the ~37 scatter+multi-feature machines. Only M275 and M272 were spot-checked. The assumption is plausible given the game-engine design, but it is not validated.

**HA-2 — D-1's blast radius is "253 machines" but may undercount variant machines.**
Per 03 §5 Symbol D-1: "253 non-variant machines declare `payouts_by_spin_type`". Per project_variants_fleet.md memory: 166 variant machines exist. The coupling audit says "253 non-variant machines" for D-1 blast radius. But variant machines delegate to their base machine's analyzer config — if variants also declare `payouts_by_spin_type` in their effective plugin set (via inheritance from the base manifest), they are also affected. The proposal and coupling audit say "253 non-variant machines" consistently, but the assumption that variant machines are fully excluded from the blast radius is not explicitly validated.

**HA-3 — `topo_sort.py` is the right file for `PluginDeclaredDepMissingError`.**
The proposal places the new class in `topo_sort.py` because two analogous classes already exist there. But `topo_sort.py`'s scope is "topological sort for plugin dependency graph" (module docstring line 1). The DECLARED_DEPS check is a runtime emit-loop check, not a graph-sort check. Placing the new exception class in `topo_sort.py` is convenient but not semantically correct.

**HA-4 — The emit-error handler (pia:5083) does not interfere with the DECLARED_DEPS RuntimeError path.**
Per the actual code at pia:5075-5080: the DECLARED_DEPS check runs in the `for _dep_key in _feature.DECLARED_DEPS:` inner loop, BEFORE the `try: _feature.emit(...)` outer try block at pia:5081. So the `RuntimeError` at pia:5077 is NOT inside the emit-error `try/except` at pia:5081-5091. This means the DECLARED_DEPS RuntimeError correctly propagates as an uncaught exception. The proposal's Region 2 design relies on this ordering being preserved. If a future restructuring wraps the entire inner loop in a broader try/except, the DECLARED_DEPS path changes behavior. This ordering dependency is undocumented.

**HA-5 — `summary["_bonus_chain_dynamics_data"]` is popped by `bonus_chain_dynamics.emit()` before the temp-key cleanup at pia:5115.**
Per BCD plugin emit() line 189: `stash: dict[str, Any] = summary.pop(_STASH_KEY)`. If BCD emit() fails (caught by emit-error handler at pia:5083), the stash pop may or may not have happened depending on where in emit() the failure occurred. If the pop happened, the cleanup at pia:5115 doesn't need to remove `_STASH_KEY` (it's already gone). If the pop didn't happen (early failure), `_STASH_KEY` remains and is cleaned up at pia:5115. This is a pre-existing subtlety, not introduced by this proposal, but the EC-6 edge case above (temp keys in topo-error JSON) is related.

---

## §7 Comparison to Rejected Alternatives

### Alternative E-1 (Fully dynamic) — rejected correctly

Proposal correctly rejects E-1: `assert ev == _compute_effective_version("M14", 1)` is trivially true. The rejection rationale is sound and confirmed by 03 §4 E-2: "loses all regression guard value." No additional critique warranted.

### Alternative E-2 (Hybrid — re-pin after each D-fix) — rejected correctly

Proposal correctly notes this "still requires a manual update after every D-commit; the problem recurs." The C6 critic demonstrated this failure mode. The rejection rationale is sound. However, the "Cons" of E-3 (does not catch accidental plugin modification) are understated. The proposal says byte-identical tests catch this — but byte-identical tests only run against specific fixture machines (M14, M275, etc.) and only validate the full summary structure, not the `effective_analyzer_version` specifically. A modification to a plugin file that happens to be idempotent (same output but different file bytes) would flip `effective_analyzer_version` but might not flip the byte-identical summary. E-2 would catch this; E-3 would not.

### Alternative A-1 (Sidecar file) — rejected correctly

Proposal correctly rejects A-1: adds new contract surface; brief specifies `summary["analyzer_init_error"]` top-level. 03 §2 Symbol A-1 confirms 0 production readers and no operator path reads the sidecar. Rejection rationale is sound.

### Alternative A-2 (Narrow try/finally for topo only) — rejected correctly

Proposal correctly rejects A-2: does not unify DECLARED_DEPS handling. Rejection rationale is sound. The two-region approach (A-3) is architecturally cleaner.

### Alternative D2-b (Manifest-level Tier 1 override) — partial rejection

Proposal rejects D2-b because it "requires manifest changes for every affected machine (~37 machines); does NOT fix the algorithmic heuristic." This is correct for Round 1. However, D2-b is actually more semantically correct: an operator who edits `mechanism_overrides.scatter_trigger_target: "NormalCollectionSpin"` in the manifest is making an explicit, auditable, machine-specific decision. The D2-a heuristic can be wrong silently (TC-2 above). The proposal defers D2-b to Cluster B (Mechanism Registry completion) — this is the right deferral, but the rejection should be stated as "deferred, not permanently rejected" since D2-b is the architecturally superior long-term solution.

### Alternative D2-c (first_st inverse mapping) — rejected reasonably

Proposal says D2-c "requires the most stash extension and depends on the chain data correctly capturing `first_st` per feature." The chain data does capture `first_st` per feature (via `chain_chunk_summaries` keys). The rejection is practical (complexity for Round 1) but the feasibility claim ("most principled but requires the most stash extension") is worth noting: D2-c is the ground-truth solution per game logic (scatter pid's triggering ST → feature name via manifest's `features_by_spin_type`). The proposal could strengthen the D2-c description to note that it would make D2-b unnecessary (algorithmic correct mapping eliminates the need for per-machine manifest overrides).

---

## §8 Beyond Prompted: Additional Flaws Found

**BF-1 — `test_c6_bonus_chain_dynamics_plugin.py:414` tests alphabetical-first with mock "AFeature"/"ZFeature" — this test also breaks on D-2.**
The test at line 414-435 (`test_emit_trigger_target_from_scatter_feature_names`) injects a stash with `scatter_feature_names: ["ZFeature", "AFeature"]` and asserts `trigger_target == "AFeature"` (alphabetically first). After D-2 with chain-count majority vote, this test needs a stash with `scatter_feature_chain_counts` to determine which feature wins. The test currently has NO `scatter_feature_chain_counts` in its stash dict. With the D-2 code sketch, `_chain_counts = stash.get("scatter_feature_chain_counts") or {}` returns `{}`, so both features get count 0, and `max()` on equal values returns the first element of `scatter_feature_names` — which is `"ZFeature"` (the list is `["ZFeature", "AFeature"]`, not sorted). Wait: `scatter_feature_names` in the stash is `["ZFeature", "AFeature"]` (as-provided, not sorted), so `max(["ZFeature", "AFeature"], key=lambda f: {}.get(f, 0))` with all-zero keys returns the LAST element seen by max() when all are equal — Python's `max()` returns the FIRST maximum found in iteration order, which is the first element of the list. So the test would get `"ZFeature"` (first in list), not `"AFeature"` (alphabetically first). The test would turn RED with a confusing failure: expected "AFeature", got "ZFeature". The proposal does not identify this test as requiring update.

This means THREE tests require updates for D-2, not one or two:
1. `test_c6_gap_3_pid_666_trigger_marker.py:160` (asserts "NewFreespin" from M275 cached fixture)
2. `test_c6_bonus_chain_dynamics_plugin.py:432` (asserts "AFeature" from alphabetical mock — will fail with chain-count logic on empty counts dict)
3. The test at `test_c6_bonus_chain_dynamics_plugin.py:437-453` (asserts `"data_inferred"` — this one may still pass if the 2-feature case still gets `"data_inferred"` even with chain-count logic)

**BF-2 — The `_safe_write_summary_json` sketch takes a `stderr_ref` parameter, but PIA main() imports `sys` inside the `except` block (`import sys as _sys` at pia:5047-5048, not at module top). The `_safe_write_summary_json` local function defined inside main() could capture `_sys` via closure if defined after that import, but the order of definition matters. If `_safe_write_summary_json` is defined BEFORE the topo-sort block (as would be natural for a local helper), `_sys` may not be in scope when the wrapper needs to print to stderr. The proposal's sketch does not address where in main() the helper is defined or how it accesses stderr.**

**BF-3 — The proposal says "3 commits total" and lists commit E as "test refactor only (no code change, no version invalidation)." But the effective_version of TESTS is not a version-hash concept — `effective_analyzer_version` is about production plugin files. Saying "no version invalidation" for Cluster E is correct, but could confuse an implementer into thinking that changing test files is always version-safe. The commit message template (§6) for Cluster E must include the blast radius section even though it says "0 machines invalidated" — this should be made explicit.**

---

## §9 Verdict

**APPROVE-WITH-REVISIONS**

### Mandatory changes before implementation begins

1. **Proposal §7**: Add `test_c6_gap_3_pid_666_trigger_marker.py:160` to the list of tests that must be updated as part of D-2. State "two tests require update" explicitly.

2. **Proposal §7 (BF-1)**: Add `test_c6_bonus_chain_dynamics_plugin.py:414-435` (`test_emit_trigger_target_from_scatter_feature_names`) to the required D-2 test updates. This test must be updated to inject `scatter_feature_chain_counts` in the mock stash, otherwise it will fail with wrong behavior (ZFeature, not AFeature).

3. **Proposal §5.2 (Q9/D-R4)**: The BCD plugin emit() must validate that `scatter_feature_chain_counts` is present in the stash when `scatter_feature_names` is non-empty. Silent fallback to alphabetical (wrong behavior) on missing stash key violates `feedback_capture_drift.md`. Raise RuntimeError (caught as feature_errors) if the key is absent.

4. **Proposal §4.4**: Add a second test specification for Region 2 (DECLARED_DEPS error path): inject a DECLARED_DEPS failure via a plugin that declares a non-existent summary key, run PIA, assert rc=1 + JSON on disk + `analyzer_init_error` key + partial plugin output from features that ran before the failing one.

5. **Proposal §5.1 (Q4/D-R5)**: Add guidance that the implementer must convert `int()` ValueError into a descriptive `RuntimeError` inside `payouts_by_spin_type.emit()` BEFORE the outer emit-error handler captures it. Do not rely on the emit-error handler to surface a cryptic "invalid literal for int()" message in feature_errors.

### Recommended but not blocking

6. Clarify that `PluginDeclaredDepMissingError` should not live in `topo_sort.py` (which is graph-ordering code) but in a more appropriate location such as a new `plugin_errors.py` or `pipeline_context.py`.

7. Brief's "5+ files" Cluster E scope description should be reconciled with proposal's "2 files require migration" conclusion — add a line to Phase 1 deliverables stating "6 remaining files confirmed no-change."

8. Re-pin commit message template to note "0 machines invalidated" explicitly for Cluster E commit, to avoid implementer confusion.

9. Clarify in §10 deferrals that D2-b (manifest-level override) is "deferred to Cluster B, not permanently rejected" — it is the architecturally superior long-term solution.

---

*Critique end.*
