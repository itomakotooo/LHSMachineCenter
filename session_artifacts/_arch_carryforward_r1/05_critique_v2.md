# 05 — Architecture Critique v2: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Role**: arch-critic (W3), v2 re-review
> **Proposal reviewed**: `04_architecture_proposal_v2.md`
> **v1 critique**: `05_critique.md`
> **Validator input**: `06_validation.md`
> **Wave 1 evidence base**: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`
> **Verdict**: APPROVE-WITH-MINOR-REVISIONS

---

## §1 Top Concerns (Summary)

Three concerns remain after v2's mandatory fixes. None require redesign; all are implementation-guidance gaps.

**TC-2-PARTIAL (d2 silent fallback — resolved in principle, new gap introduced)**
v2's RuntimeError on missing stash key is correct. But the RuntimeError fires at the TOP of the `if scatter_marker_pids and scatter_feature_names:` block, before the `len == 1` branch. This means the guard triggers for ALL stash usages including the single-feature case. The existing test fixtures using `_make_stash()` (which produces 1 feature, no `scatter_feature_chain_counts` key) will throw a RuntimeError during Phase 2 impl, not just the 2-feature tests enumerated in v2 §7. The v2 spec says "3 tests require update" and "impl team must grep for ALL occurrences" — the grep instruction is correct but the count of 3 is wrong. The actual count is larger.

**SQ-1 (fallback_no_chain_data and feedback_invariant_with_fallback_hides_drift)**
v2 specifies `"fallback_no_chain_data"` as a valid output with rc=0. Per `feedback_invariant_with_fallback_hides_drift.md`, any `_unattributed_*` or "garbage-bucket" field that silently absorbs bad data must be a warning signal, not an accounting mechanism. `fallback_no_chain_data` emitted as `trigger_target_confidence` without a companion `feature_errors` entry is exactly this pattern: the operator reading the panel sees a trigger_target value but must specifically look for the confidence field to know it is degraded. This is the invariant-with-fallback-hides-drift failure mode applied to confidence fields. v2's §12 SQ-1 acknowledges this but leaves it open for the critic to resolve.

**SQ-2 (Region 2 inject-bug mechanism unresolved)**
v2 §12 SQ-2 explicitly asks whether the Region 2 test inject-bug requires subprocess or can run in-process. The answer has a correct resolution available (see §2 Q-SQ2 below) but the proposal leaves it to the impl team. Given `feedback_subprocess_import_suicide_and_module_globals.md`, the answer affects how the test is written, and an impl team that gets it wrong creates a test that appears green but cannot catch the actual regression.

---

## §2 Part A — Resolution Check: v1 Q1–Q12 + 5 Top Concerns

### Mandatory Fix 1 — TC-1/B1+B2 (D-2 test list expanded to 3 tests with file:line)

**v1 requirement**: enumerate `test_c6_gap_3_pid_666_trigger_marker.py:160` and `test_c6_bonus_chain_dynamics_plugin.py:432` alongside the already-listed BCD test. Three tests total with file:line.

**v2 response** (§7, "[v2 revised — Fix 1: 3 tests, not 1]"): v2 enumerates exactly three tests in a summary table with file, line, old assertion, new assertion, and reason.

**Verification of cited paths**:
- `test_c6_gap_3_pid_666_trigger_marker.py:160` — confirmed by direct read. Line 160: `assert notes.get("trigger_target") == "NewFreespin"`. The test method is named `test_pid_666_trigger_target_is_new_freespin`. Both the assertion and the method name must change. v2 §7 correctly states both.
- `test_c6_bonus_chain_dynamics_plugin.py:432` — confirmed by direct read. Line 432: `assert row_666["notes"]["trigger_target"] == "AFeature"`. Fixture at lines 416-419 uses `["ZFeature", "AFeature"]` (unsorted), no `scatter_feature_chain_counts`. v2 §7 correctly identifies both problems (unsorted list + missing key) and specifies the corrective fixture.
- Third test (`test_c6_bonus_chain_dynamics_plugin.py:437-453 region`) — v2 §7 correctly flags this as "verify whether this test also lacks `scatter_feature_chain_counts`." Confirmed by direct read: `test_emit_trigger_target_confidence_data_inferred` (line 437) uses `self._make_stash()`. `_make_stash()` (line 289-303) returns `scatter_feature_names: ["NormalCollectionSpin"]` (single feature). With v2's RuntimeError fired at the top of the `if scatter_marker_pids and scatter_feature_names:` block, this test WILL also fail — the RuntimeError fires before the `len == 1` branch.

**New gap found in TC-1 fix (v2-introduced)**:
The v2 code sketch (§5.2) places the RuntimeError check OUTSIDE and BEFORE the `len == 1` / `else` branches:

```python
if scatter_marker_pids and scatter_feature_names:
    if "scatter_feature_chain_counts" not in stash:
        raise RuntimeError(...)           # fires for ANY len, including len=1
    _chain_counts = stash[...]
    if len(scatter_feature_names) == 1:   # only reached if key is present
        ...unique...
    else:
        ...data_inferred...
```

`_make_stash()` returns `scatter_feature_names: ["NormalCollectionSpin"]` (len=1) with NO `scatter_feature_chain_counts`. Any test that calls `_make_stash()` with a non-empty `scatter_marker_pids` context will trigger the RuntimeError. From direct code inspection, the following tests use `_make_stash()` with pid 666 in scatter_marker_pids:
- `test_emit_trigger_marker_true_for_scatter_pid` (line 376) — fires RuntimeError
- `test_emit_trigger_target_confidence_data_inferred` (line 437) — fires RuntimeError
- `test_emit_non_trigger_rows_omit_trigger_target_confidence` (line 456) — uses `_make_stash()` but with pid 1 (non-scatter); the `if scatter_marker_pids and scatter_feature_names:` block fires only when the pid IS in scatter_marker_pids AND scatter_feature_names is non-empty. With scatter_marker_pids={"666"} and pid_rows=[{"payout_id":"1",...}], the trigger_target logic still runs (it's per-PID? no — looking at the plugin structure, the block runs once per emit call, checking against the stash, not per row). This requires careful reading of the actual plugin emit() to determine.

The v2 spec says "the impl team must grep... for ALL occurrences." This is the right instruction but leaves the count undefined. v2's stated count of 3 is almost certainly wrong; the actual count is higher. The impl team, reading §7, will think "3 tests" and stop after updating 3, leaving the others RED on first CI run.

**Verdict**: PARTIAL — the mandatory fix is structurally correct (right file:line, right assertion changes, correct fixture remediation), but the stated count of "3 tests" is incorrect because the RuntimeError placement in the code sketch affects more existing tests than enumerated. The `scatter_feature_chain_counts` key must also be added to `_make_stash()` itself, or the RuntimeError guard must be conditioned on `len >= 2` only (which would change the spec intent). The impl team needs explicit guidance on this.

---

### Mandatory Fix 2 — TC-2 (silent fallback — RuntimeError + 3 confidence levels)

**v1 requirement**: BCD plugin must raise RuntimeError when `scatter_feature_chain_counts` is missing; 3 confidence levels must be documented.

**v2 response** (§5.2 "[v2 revised — Fix 2]"): Three confidence levels are documented in a table (`unique` / `data_inferred` / `fallback_no_chain_data`). The missing-key RuntimeError is specified with exact message content. The code sketch places the RuntimeError at the top of the `if scatter_marker_pids and scatter_feature_names:` block.

**The explicit error on missing stash key**: The v2 sketch is correct in intent. When `scatter_feature_chain_counts` is absent and scatter_feature_names is non-empty, a RuntimeError is raised. This is caught by the emit-error handler at `pia:5083` and written to `feature_errors["bonus_chain_dynamics"]`. This satisfies `feedback_no_silent_swallow.md` and `feedback_capture_drift.md`.

**The fallback_no_chain_data level vs. feedback_invariant_with_fallback_hides_drift.md**:
v2 §5.2 defines `"fallback_no_chain_data"` as the state where the stash key IS present but all chain counts are zero. The run continues with rc=0 and the operator sees `trigger_target_confidence = "fallback_no_chain_data"`. Per `feedback_invariant_with_fallback_hides_drift.md` (2026-05-12 M274 lesson): "任何 `_unattributed_*` / `_other` / `else` 这类垃圾桶 label 都要被设计成告警信号而非关账机制; invariant verifier 必须同步检查 fallback share." The `fallback_no_chain_data` confidence is a garbage-bucket label in the `trigger_target_confidence` field. An operator must specifically inspect this field to detect it; it does not surface automatically. v2 §12 SQ-1 acknowledges this is unresolved. The question is whether the confidence field alone is sufficient or whether a companion `feature_errors["bonus_chain_dynamics_confidence_degraded"]` warning entry is needed.

**Assessment of the three confidence levels**:
- `"unique"` (len=1): deterministic, correct.
- `"data_inferred"` (len>=2, at least one non-zero count): majority-vote heuristic, documented as such. Correctly emitted.
- `"fallback_no_chain_data"` (len>=2, all counts zero): alphabetical-first, rc=0. This IS a silent fallback by the standard of `feedback_invariant_with_fallback_hides_drift.md` unless a companion warning is emitted elsewhere. Leaving SQ-1 "for the critic to resolve" is appropriate; this critique resolves it below.

**Resolution of SQ-1**: `fallback_no_chain_data` in `trigger_target_confidence` is NOT sufficient per the memory invariant. The companion field approach is: in the `fallback_no_chain_data` branch, additionally write `summary["feature_errors"]["bonus_chain_dynamics_confidence"] = "fallback_no_chain_data: all chain counts are zero; trigger_target is alphabetical-first, not data-driven"`. This makes the degradation visible in the `feature_errors` panel (which operators already monitor for degradation signals) without affecting the main `trigger_target` field.

However, this critique notes it does not "fix" — it flags. The designer must decide. The verdict is PARTIAL because the fallback path is technically correct but conflicts with the memory invariant.

**Verdict**: PARTIAL — RuntimeError on missing key is correctly specified. The `fallback_no_chain_data` confidence level produces a silent fallback that conflicts with `feedback_invariant_with_fallback_hides_drift.md` (SQ-1 unresolved in the proposal). The three confidence levels are internally consistent but the fallback_no_chain_data case needs a companion warning signal per the memory.

---

### Mandatory Fix 3 — TC-3 (Region 2 test with partial-state semantics)

**v1 requirement**: Add a Region 2 test specifying: rc=1 + JSON on disk + `analyzer_init_error` key + partial-plugin-output fields from pre-failure features.

**v2 response** (§4.4 "[v2 revised — TC-3 fix]"): A full Region 2 test spec is present. Seven assertions are listed, including assertion 7: "at least one OTHER plugin's output key IS present in the JSON (verifying partial-emit output is preserved)." The inject-bug recipe for Region 2 is: monkeypatch the emit loop to skip the DECLARED_DEPS check — then assert JSON does NOT exist and rc != 0 — restore and assert GREEN.

**Partial-state semantics**: v2 §4.3 explicitly selects option (a) (keep partial + annotate with `region=2`). The rationale cites three reasons. The `region` field distinguishes Region 1 (pre-emit) from Region 2 (mid-emit). The `affected_plugin` field identifies the break point. The on-disk JSON contract is documented.

**Verification of assertion coverage**:
- rc=1: covered (assertion 1)
- JSON on disk: covered (assertion 2)
- `analyzer_init_error` key present: covered (assertion 3)
- `error_type == "PluginDeclaredDepMissingError"`: covered (assertion 4)
- `region == 2`: covered (assertion 5)
- `affected_plugin == FEATURE_ID of injected plugin`: covered (assertion 6)
- At least one prior plugin's output key present (partial-emit validation): covered (assertion 7)

**Inject-bug recipe for Region 2**: The v2 spec says "monkeypatch the emit loop so the DECLARED_DEPS check is skipped entirely." Per `feedback_subprocess_import_suicide_and_module_globals.md`, monkeypatching inside the PIA main() function body requires either (a) running in-process (imports PIA main directly) or (b) subprocess with a patched version. v2 §12 SQ-2 explicitly leaves this unresolved. The inject-bug recipe is specified correctly in terms of WHAT to do but not HOW to do it mechanically without triggering the subprocess-import-suicide footgun. This is a gap but does not invalidate the test spec.

**Does the spec cover all of Region 2's failure mode, or only the DECLARED_DEPS subset?**
Region 2 covers exactly the DECLARED_DEPS check inside the emit loop. The test correctly exercises this path. There is no other failure mode in Region 2 — the only error that fires before emit() within the emit loop is the DECLARED_DEPS check. The emit() itself, if it fails, goes to `feature_errors` (Path 3), not to `analyzer_init_error`. The Region 2 spec is complete for its stated scope.

**Verdict**: Resolved — the Region 2 test is fully specified with all required assertions and correct partial-state contract. The inject-bug mechanism (SQ-2) is unresolved but is a test-impl question, not a spec gap. Mark as RESOLVED with the SQ-2 caveat.

---

### v1 Q1 — Phase order A→D merge conflict risk

**v2 response**: Carried verbatim. v2 §9 Phase 3 deliverables explicitly sequences D before A. The D-4 change is at PIA:4817; the A change is at PIA:5044-5080. Non-overlapping regions, mechanical merge conflict unlikely.

**Assessment**: The v1 verdict was PARTIAL because the same-file risk was unaddressed. v2 still carries verbatim — no new address. However, the deliverables section (§9) sequences D before A and names the exact line numbers. An impl team following the deliverables order will apply D-4 first, then A on a clean D base. This is sufficient for Round 1.

**Verdict**: PARTIAL (same as v1) — merge conflict is unlikely due to non-overlapping regions, but the spec still does not explicitly call out "D-4 modifies PIA:4817; A modifies PIA:5044-5080; verify no conflict" as a Phase 3 implementation step.

---

### v1 Q2 — Region 2 partial summary silent misuse

**v2 response**: Resolved by the TC-3 fix. The partial-state contract is now explicitly "option (a): keep partial + annotate." The `region=2` field distinguishes partial from complete. The backend at `_batch_gen_worker.py:154` short-circuits on rc=1 before reading the JSON. The operator-side risk is acknowledged but the judgment is that `region=2` in `analyzer_init_error` is sufficient signaling.

**Assessment**: The backend consumption path is safe. The operator-side risk is a judgment call, not a design flaw. The TC-3 test's assertion 7 explicitly validates the partial-state contract. This is adequately addressed for Round 1.

**Verdict**: Resolved.

---

### v1 Q3 — D-2 chain-count semantic basis

**v2 response**: Carried verbatim. The proposal acknowledges the heuristic is correct for M275 and M272 but does not extend validation to the ~37 affected machines.

**Assessment**: Still PARTIAL. Only 2 of ~37 machines validated. The proposal notes this in §11 Q2 (surviving open question). The risk is accepted for Round 1 with the understanding that D2-b (manifest override, architecturally superior) is deferred to Cluster B. This is an acceptable Round 1 trade-off per the design's explicit acknowledgment.

**Verdict**: PARTIAL — heuristic validated on 2 machines, assumed correct for 37. Risk accepted and documented. Acceptable for Round 1.

---

### v1 Q4 — D-1 ValueError silent capture by emit-error handler

**v2 response**: §5.1 now includes a defensive pre-validation sketch with `isdigit()` guard before the sort call. The sketch raises a descriptive `RuntimeError` before the emit-error handler catches a bare `ValueError`. This is exactly the fix requested in v1 (verdict was NOT ADDRESSED).

**Assessment**: The fix is structurally correct. The pre-validation raises `RuntimeError` with a descriptive message BEFORE the sort call. The emit-error handler at `pia:5083` will catch this `RuntimeError` and write it to `feature_errors["payouts_by_spin_type"]` with a human-readable message. This satisfies `feedback_capture_drift.md`.

**Verdict**: Resolved.

---

### v1 Q5 — Cluster E structural differential: "differs by exactly multiplier_wild"

**v2 response**: Carried verbatim. The proposal acknowledges E-3 does not catch "someone accidentally modified a plugin file." The byte-identical tests are cited as the secondary guard.

**Assessment**: Same as v1 verdict (PARTIAL). The acknowledged trade-off is acceptable. The byte-identical tests (test_c5_byte_identical, test_c6_byte_identical) provide the secondary plugin-modification guard. This is not a blocker.

**Verdict**: PARTIAL — same as v1. Trade-off is acknowledged and acceptable.

---

### v1 Q6 — PluginDeclaredDepMissingError file placement

**v2 response**: v2 §10 (deferrals) explicitly defers the relocation of `PluginDeclaredDepMissingError` from `topo_sort.py` to `pipeline_context.py` or a new `plugin_errors.py`. The Phase 3 deliverables (§9) place it in `topo_sort.py` for Round 1. The `error_type` field's diagnostic value (different class name) is documented in §4.3 A-3b.

**Assessment**: The v1 recommended-but-not-blocking item (Q6) is now explicitly called out in §10 deferrals with the justification: minimal delta, relocatable in Cluster C without breaking JSON consumers. Adequate for Round 1.

**Verdict**: Resolved (deferred correctly with justification).

---

### v1 Q7 — D-4 fix location stability

**v2 response**: Carried verbatim. PIA inline is the selected location. Cluster C is the planned home for restructuring.

**Assessment**: PARTIAL — same as v1. Acceptable for Round 1.

**Verdict**: PARTIAL — same as v1. Correct choice for Round 1.

---

### v1 Q8 — 3-commit overhead justification

**v2 response**: Carried verbatim. The 3-commit structure maps 1:1 to impl-* loops per `feedback_impl_team_required.md`.

**Assessment**: Adequately addressed in v1; no change. Resolved.

**Verdict**: Resolved.

---

### v1 Q9 — D-2 silent fallback on missing stash key

**v2 response**: This was the NOT ADDRESSED verdict in v1. v2 §5.2 now specifies the RuntimeError on missing key. See TC-2 resolution above.

**Verdict**: PARTIAL — RuntimeError is specified correctly. The `fallback_no_chain_data` path creates a new silent-fallback concern per `feedback_invariant_with_fallback_hides_drift.md`.

---

### v1 Q10 — Backend reader of analyzer_init_error

**v2 response**: Carried verbatim. 0 production readers confirmed by coupling audit.

**Verdict**: Resolved (same as v1).

---

### v1 Q11 — File enumeration for Cluster E

**v2 response**: Carried verbatim. 2 files require migration; 6 files confirmed no-change; §9 Phase 1 deliverables explicitly state "6 remaining files confirmed no-change."

**Verdict**: Resolved — the §9 deliverables addition explicitly addresses the implementer confusion risk.

---

### v1 Q12 — D-3 testability with 0 fleet machines

**v2 response**: Carried verbatim. Unit test with mock stash; no fleet data dependency.

**Verdict**: Resolved (same as v1).

---

### v1 TC-4 — Cluster E inject-bug requires out-of-band manifest edit

**v2 response**: Carried verbatim. The inject-bug recipe (§7) still requires "temporarily add `multiplier_wild` to M14's manifest." This is explicitly a manifest change outside the test suite.

**Assessment**: v1 said "either add a second automatable inject-bug path or explicitly accept this as a known CI gap." v2 does not add an automatable alternative. The manifest-edit recipe is not automatable in CI. This is a known gap.

However, the validator (06 §8) independently verified the inject-bug recipe works:
> "Step 1: Add 'multiplier_wild' to M14.json... Step 3: M14 EV now incorporates multiplier_wild hash -> equals M275 EV -> FAIL."

The gap is real but not blocking — the differential assertion is validated as non-trivial. The CI automation limitation is acceptable for Round 1 since the structural property is the real invariant (manual verify of inject-bug is sufficient before commit).

**Verdict**: PARTIAL — same as v1. Acknowledged and accepted for Round 1.

---

### v1 TC-5 — PluginDeclaredDepMissingError distinguishability

**v2 response**: v2 §4.3 (A-3b) now explicitly states the new class takes `plugin: str` and `missing_dep_key: str` (summary key, not FEATURE_ID). The `error_type` field in the JSON is `"PluginDeclaredDepMissingError"`. The operator sees a different class name from `"PluginMissingDependencyError"` and the `message` field contains the summary key name, not a FEATURE_ID.

**Assessment**: The diagnostic distinction is now explicit in both the exception signature and the message content. This resolves the v1 concern that the classification "adds noise without diagnostic value."

**Verdict**: Resolved.

---

### v1 BF-1 and BF-2

**BF-1** (test_c6_bonus_chain_dynamics_plugin.py:414-435 fixture): Addressed as Test update 2 of 3 in v2 §7. The fixture fix and sort are specified. See TC-1 verdict for the new gap about wider RuntimeError scope.

**BF-2** (stderr_ref and `_sys` import order): v2 §4.3 explicitly states "The `stderr_ref` parameter receives `sys.stderr` at call time (not captured via closure from the top of main) to avoid the import-order risk flagged in BF-2 of the critique." Resolved.

---

## §3 Part B — New Problems Introduced by v2

### B-New-1 — RuntimeError placement causes wider test breakage than v2 enumerates

**Finding**: The v2 code sketch places the RuntimeError check at the TOP of the `if scatter_marker_pids and scatter_feature_names:` block, before the `len == 1` branch. `_make_stash()` (the shared helper at line 289-303) produces `scatter_feature_names: ["NormalCollectionSpin"]` (single feature, `applicable=True`) with NO `scatter_feature_chain_counts` key. Any emit() call that receives this stash with a non-empty `scatter_marker_pids` triggers the RuntimeError before the `len == 1` unique-branch.

Tests using `_make_stash()` that pass a pid-in-scatter_marker_pids context:
- `test_emit_trigger_marker_true_for_scatter_pid` (line 376) — `_make_stash()` + pid 666 → RuntimeError
- `test_emit_trigger_target_confidence_data_inferred` (line 437) — `_make_stash()` + pid 666 → RuntimeError

These are NOT in v2's "3 tests require update" enumeration.

**Two resolution paths** (flagged, not fixed — designer decides):

Path A: Condition the RuntimeError on `len >= 2` only (i.e., move the check inside the `else` branch). The `len == 1` (unique) path does not need `scatter_feature_chain_counts` since no majority vote is needed. This narrowing of the guard is semantically correct: the key is only required for the majority-vote heuristic, not for the deterministic single-feature case. Under this path, `_make_stash()` tests are unaffected.

Path B: Keep the RuntimeError at the top (all cases), and update `_make_stash()` to include `scatter_feature_chain_counts: {"NormalCollectionSpin": 908}` (matching the chain_count in the stash). Under this path, all tests using `_make_stash()` gain the new key automatically and the RuntimeError does not fire.

The implication for the spec: v2 §7's "3 tests require update" instruction is incorrect under Path A or B as currently written. Under Path A, `test_emit_trigger_target_from_scatter_feature_names` (line 414, 2-feature case) still requires update; the `_make_stash()` tests do not. Under Path B, `_make_stash()` itself requires update (touching all ~8 tests that use it, but the update is a single addition to the helper).

**Verdict**: This is a NEW issue introduced by v2. It is not a design flaw but a spec-impl gap in the test update enumeration that will cause the impl team to under-update and produce CI failures on the first commit.

---

### B-New-2 — PropagationPath of RuntimeError through Cluster A's two-region try/finally (Phase ordering correctness)

**Question from brief**: Does the new RuntimeError (from d2, inside BCD's emit()) propagate cleanly through Cluster A's two-region try/finally?

**Analysis**: BCD's emit() RuntimeError is caught by the emit-error handler at `pia:5083` (`try: _feature.emit(...); except Exception: summary["feature_errors"][...] = str(exc)`). This is Path 3 (already graceful per the proposal). Cluster A's two-region try/finally (Region 1 wrapping the topo-sort block, Region 2 wrapping the DECLARED_DEPS block) does not wrap the emit loop itself. The emit loop is in Path 3, which already handles exceptions gracefully. Therefore the BCD RuntimeError propagates through the emit-error handler, not through Cluster A's try/finally.

**Does Phase 2 (D) work in a world where Phase 3 (A) hasn't shipped?**
Phase 2 ships BCD's RuntimeError on missing stash. This RuntimeError goes to `feature_errors["bonus_chain_dynamics"]`. Phase 3 (A) adds the `_safe_write_summary_json` call on the pre-emit error paths (topo-sort + DECLARED_DEPS). These are independent paths. Phase 2 without Phase 3 is a valid deployed state: BCD gracefully degrades; the topo-sort/DECLARED_DEPS paths still don't write JSON on error (pre-A behavior). This is acceptable because the A-fix is additive (it adds a new write on previously-unhandled paths). Phase 2 without Phase 3 produces no regression relative to the pre-D state.

**Verdict**: No issue — the RuntimeError propagation is clean and Phase 2 without Phase 3 is a valid intermediate state. This concern is RESOLVED.

---

### B-New-3 — 3 confidence levels: can a code path produce the wrong one?

**Question from brief**: Could a code path produce a confidence level when another would be more accurate?

**Code sketch analysis** (v2 §5.2):

```
if scatter_marker_pids and scatter_feature_names:
    if key not in stash: raise RuntimeError
    _chain_counts = stash[key]
    if len(scatter_feature_names) == 1:
        confidence = "unique"
    else:
        _max = max(chain_counts.get(f,0) for f in scatter_feature_names)
        if _max == 0: confidence = "fallback_no_chain_data"
        else: confidence = "data_inferred"
elif scatter_marker_pids:
    confidence = "unknown"
else:
    confidence = None
```

**Mis-production scenarios**:

Scenario 1: `scatter_feature_names` contains features where some have data (count > 0) and some do not, but the feature with the highest count is not the scatter trigger target. The code correctly emits `"data_inferred"` — the confidence level is accurate (it IS inferred from data). The inferred value may be wrong for the ~37 machines not validated, but the confidence label is honest about its method.

Scenario 2: `scatter_feature_names = ["OnlyFeature"]` and chain count for that feature is 0. The code emits `"unique"` (len == 1 branch fires first). This is correct — with exactly one possible feature, it is deterministic regardless of chain count. The confidence label `"unique"` is accurate (there was only one option).

Scenario 3: `scatter_feature_names` contains 2 features; `scatter_feature_chain_counts` is present but counts are identical and non-zero (e.g., both=50). `_max = 50 > 0` → `"data_inferred"`. The feature selected is the first element in the sorted list (alphabetically first, per the stash construction). The confidence says `"data_inferred"` but the actual selection was alphabetical. This is a subtle mis-production: `"data_inferred"` implies chain counts drove the decision, but in a tie, alphabetics drove it. The v2 spec acknowledges this in §5.2 ("on a tie, max() returns the first element of the sorted list — deterministic behavior, documented in plugin docstring"). The confidence level `"data_inferred"` is technically accurate (counts were consulted; the max of equal counts is still the max), but could mislead an operator who thinks "data_inferred" means "unambiguous chain data."

**Assessment of scenario 3**: This is a pre-existing subtlety, not introduced by v2 but also not resolved by v2. A fourth confidence level `"data_inferred_tied"` would be more accurate for this case. However, this is a minor semantic refinement that the v2 proposal correctly defers (it is not a correctness bug, only a precision gap). Flagging it for future Cluster B consideration.

**Verdict**: No critical mis-production found. Scenario 3 is a minor semantic gap (tie-case should ideally emit a distinct confidence label). Not blocking for Round 1.

---

### B-New-4 — Partial-state contract vs. feedback_invariant_with_fallback_hides_drift.md

**Question from brief**: Does option (a) (keep partial + annotate) conflict with the memory invariant?

**Memory invariant** (`feedback_invariant_with_fallback_hides_drift.md`): "任何 `_unattributed_*` / `_other` / `else` 这类垃圾桶 label 都要被设计成告警信号而非关账机制." The specific concern is: do the partially-emitted plugin keys in the on-disk JSON look like a valid complete summary?

**Analysis**: The partial summary under option (a) contains:
- Valid plugin output from features emitted before the failing plugin
- `analyzer_init_error` with `region=2` and `affected_plugin`
- Raw `_`-prefixed stash keys (not yet cleaned up)

The `analyzer_init_error` key IS the explicit warning signal. The `region=2` value distinguishes this from a complete run. Unlike a `_unattributed_*` bucket that silently absorbs bad data in a field that looks legitimate, the `analyzer_init_error` key is an out-of-band signal that an operator must explicitly ignore to misread the partial summary.

The comparison to `feedback_invariant_with_fallback_hides_drift.md` is not quite apt here: the memory warns about fallback accounting buckets that hide drift IN the normal data fields. Option (a)'s `analyzer_init_error` is a dedicated error field, not a normal data field that silently absorbs errors. The risk is operator discipline, not structural design — an operator who reads `payouts_by_spin_type` results from a partial summary is making a workflow error, not a design-level error.

**Verdict**: The partial-state design (option a) does NOT violate `feedback_invariant_with_fallback_hides_drift.md`. The memory warns about in-band fallback accounting; `analyzer_init_error` is an explicit out-of-band signal. No conflict.

---

### B-New-5 — SQ-2: Region 2 inject-bug mechanism (in-process vs. subprocess)

**v2 SQ-2**: Asks whether monkeypatching the DECLARED_DEPS emit loop works in-process.

**Analysis per `feedback_subprocess_import_suicide_and_module_globals.md`**: The memory documents that `virtual_app.py`'s module-top `build_virtual_app()` caused subprocess-import suicide. The concern is: does importing and calling PIA `main()` in-process cause module-global side effects?

For the Region 2 inject-bug, the approach is:
1. Register a test plugin with `DECLARED_DEPS = ("nonexistent_key",)` and `REQUIRES = ()` into a TEMPORARY plugin registry (not the global registry).
2. Run PIA against this temporary registry (not monkeypatching PIA's internal structures).

This is structurally equivalent to the Region 1 test (inject a cyclic plugin pair into a fresh temporary registry). Per 01 §2.7 ("test file header"), the existing `test_c1_init_error_surfacing.py` runs in-process. The in-process approach is feasible for Region 2 IF the test plugin is registered into a temporary registry, not the global one. The `feedback_subprocess_import_suicide_and_module_globals.md` concern applies to tests that call `main()` unconditionally importing everything — a local temp-registry injection avoids this.

**Verdict**: The inject-bug can be achieved in-process by injecting into a temporary plugin registry (same pattern as Region 1). Subprocess is not required. The v2 spec's inject-bug recipe is implementable. SQ-2 is resolved: in-process is preferred per `feedback_subprocess_import_suicide_and_module_globals.md`.

---

## §4 Migration Risk Inventory — Delta from v1

v1's migration risk inventory (§4) is carried forward. The v2 revisions add the following new risks:

**v2-MR-1 — D-2 RuntimeError scope wider than documented (see B-New-1)**
Risk: impl team reads "3 tests require update," updates 3 tests, and commits. CI RED on first push due to `_make_stash()`-based tests encountering the RuntimeError. This is not a design risk — it is an implementation guidance gap.
Mitigation: The impl team must grep `test_c6_bonus_chain_dynamics_plugin.py` for ALL stash constructions that include `scatter_feature_names` with applicable=True and non-empty scatter_marker_pids context, not just the 3 enumerated.

**v2-MR-2 — fallback_no_chain_data confidence emitted without companion warning (SQ-1)**
Risk: A machine arrives at `fallback_no_chain_data` state (stash present, all counts zero). The operator does not notice because `trigger_target_confidence` is not a prominently-monitored field. The incorrect alphabetical trigger_target is used operationally.
Mitigation: Companion `feature_errors` warning entry (as described in SQ-1 resolution above). Not yet specified in v2.

**v2-MR-3 — `_safe_write_summary_json` stderr_ref defined but not in scope (v2 addition)**
v2 §4.3 adds `stderr_ref=_sys.stderr` as a parameter to `_safe_write_summary_json`. v2 also says the helper must be defined BEFORE the topo-sort block. If `_sys` is imported as `import sys as _sys` inside the topo-sort except block (the current pattern per 06 §0 PIA control flow), and `_safe_write_summary_json` is defined before the topo-sort block as a local function, then `_sys` is not yet bound when the helper is defined. The BF-2 fix (pass `sys.stderr` at call time) addresses this — but the implementation must ensure the helper receives `sys.stderr` directly (not via closure) and that the sys import is at module top or before the helper definition. The Phase 3 deliverables (§9) name the helper but do not specify the import order.

---

## §5 Edge Cases Not Covered by v2

**EC-New-1 — `_make_stash()` helper is the source of the undercounted test breakage**
The `_make_stash()` helper at line 289-303 is used by 8+ tests. Under v2's RuntimeError at the top of the scatter block, all uses of `_make_stash()` with a scatter context (pid in scatter_marker_pids) break. The proposal's "grep for all occurrences" instruction is correct but does not identify the `_make_stash()` helper itself as the root cause. Updating `_make_stash()` to include `scatter_feature_chain_counts` would fix all downstream tests in one place. This edge case is not covered.

**EC-New-2 — `"unknown"` confidence in the code sketch is not in the 3-level table**
v2 §5.2's three-confidence table documents `unique`, `data_inferred`, and `fallback_no_chain_data`. But the code sketch also contains:
```python
elif scatter_marker_pids:
    trigger_target = None
    trigger_target_confidence = "unknown"
```
`"unknown"` is a fourth output value not documented in the confidence table. It applies when scatter_marker_pids is non-empty but scatter_feature_names is empty (M274-like machines). This edge case exists in the current codebase (carried forward from C6) and is correct, but the v2 three-level table omits it, making the documentation incomplete.

**EC-v1-EC6 (carried)** — Topo-error JSON includes `_`-prefixed temp stash keys. Not addressed by v2; still valid.

---

## §6 Hidden Assumptions — Delta from v1

**HA-New-1 — The RuntimeError guard applies equally to len=1 and len>=2 cases**
v2 implicitly assumes the `scatter_feature_chain_counts` key is required for ALL scatter machines (not just multi-feature ones). The stash extension at `pia:4862` adds the key unconditionally when `scatter_feature_names` is non-empty. This means single-feature machines (d3 path) also produce the `scatter_feature_chain_counts` key, even though they don't need it. The key's presence on single-feature machines is harmless but adds unnecessary stash data. More critically, if the implementation uses Path A resolution (RuntimeError only on len>=2), the stash extension can conditionally omit the key for len=1 machines, reducing waste. Neither path is wrong, but they have different compatibility with existing tests.

---

## §7 Comparison to Rejected Alternatives — Delta from v1

**D2-b (manifest-level override)**: v2 §5.2 adds the explicit statement "D2-b is deferred to Cluster B (Mechanism Registry completion), NOT permanently rejected." The v1 critique requested this clarification. The v2 text now reads: "D2-b is deferred to Cluster B... D2-a can be superseded gracefully." This addresses the v1 recommendation.

**Verdict**: Resolved.

---

## §8 New Stress Questions

### SQ-A — Does the v2 RuntimeError guard break `test_emit_trigger_marker_true_for_scatter_pid` (line 376)?

The `test_emit_trigger_marker_true_for_scatter_pid` test uses `_make_stash()` which returns `scatter_feature_names: ["NormalCollectionSpin"]` and no `scatter_feature_chain_counts`. With v2's RuntimeError at the top of the scatter block (fires for any non-empty `scatter_feature_names`), this test breaks. Its only assertion is `is_trigger_marker == True` — it has nothing to do with trigger_target or chain counts. The RuntimeError fires before the `is_trigger_marker` assignment, so the test fails for entirely the wrong reason.

**Designer's likely answer**: "The impl team should add `scatter_feature_chain_counts` to `_make_stash()`." This is correct and sufficient — one line change to the helper fixes all downstream tests. But v2 §7 does not say this.

**Why it's insufficient**: An impl team reading "3 tests require update" will not update `_make_stash()` because it's a helper, not a test function. The test suite will have unexpected RED tests that appear unrelated to the D-2 change.

**Verdict**: PARTIAL — the root cause is identifiable by grepping, but the v2 spec's count of 3 and the explicit "grep for ALL occurrences" instruction are insufficient to prevent the impl team from under-updating.

---

### SQ-B — Is `"unknown"` confidence documented and tested?

The `"unknown"` value appears in the code sketch (§5.2) for the `elif scatter_marker_pids:` branch (scatter pids exist but no feature names). The three-confidence table (§5.2) does not list it. The `_VALID_CONFIDENCE_VALUES` constant in `test_c6_gap_3_pid_666_trigger_marker.py` (line 171 reference) must include `"unknown"` for the `test_pid_666_trigger_target_confidence_valid` test to pass. If v2's three-confidence table is used as the source of truth for implementing `_VALID_CONFIDENCE_VALUES`, the impl team may remove `"unknown"` from the valid set, breaking M274-like machines.

**Designer's likely answer**: "The `elif scatter_marker_pids:` branch was not changed in D-2. The `"unknown"` value pre-exists. `_VALID_CONFIDENCE_VALUES` already includes it."

**Why this is sufficient**: If `_VALID_CONFIDENCE_VALUES` already includes `"unknown"` and the `elif` branch is not changed, there is no regression. The documentation gap (missing from the three-confidence table) is cosmetic.

**Verdict**: PARTIAL — `"unknown"` should be added to the confidence table for completeness, but no functional regression is expected if the elif branch is not modified.

---

## §9 Verdict

**APPROVE-WITH-MINOR-REVISIONS**

### Summary of mandatory/partial/resolved items

| Item | v1 Verdict | v2 Verdict | Notes |
|---|---|---|---|
| TC-1 (test list file:line) | Required fix | PARTIAL | Files/lines correct; count of 3 is wrong; `_make_stash()` must also be updated |
| TC-2 (silent fallback) | Required fix | PARTIAL | RuntimeError correct; `fallback_no_chain_data` needs companion `feature_errors` warning per memory |
| TC-3 (Region 2 test) | Required fix | Resolved | Full 7-assertion spec; inject-bug recipe correct; SQ-2 resolved as in-process |
| TC-4 (Cluster E inject-bug) | Recommended | PARTIAL | Same as v1; accepted for Round 1 |
| TC-5 (error class distinguishability) | Recommended | Resolved | `missing_dep_key: str` distinguishes from `PluginMissingDependencyError` |
| Q1 (phase order merge conflict) | PARTIAL | PARTIAL | Non-overlapping regions; acceptable for Round 1 |
| Q2 (Region 2 partial summary) | PARTIAL | Resolved | TC-3 fix covers this |
| Q3 (D-2 semantic basis) | PARTIAL | PARTIAL | 2 of ~37 validated; accepted risk |
| Q4 (D-1 ValueError handler) | NOT ADDRESSED | Resolved | Pre-validation sketch added in §5.1 |
| Q5 (E-3 structural assertion completeness) | PARTIAL | PARTIAL | Same as v1; acceptable |
| Q6 (error class placement) | Recommended | Resolved | Deferred to Cluster C in §10 |
| Q7 (D-4 stability) | PARTIAL | PARTIAL | Same as v1; Cluster C |
| Q8 (3-commit overhead) | Resolved | Resolved | |
| Q9 (D-2 silent fallback) | NOT ADDRESSED | PARTIAL | RuntimeError correct; fallback_no_chain_data warning gap |
| Q10 (backend reader) | Resolved | Resolved | |
| Q11 (file enumeration) | Resolved | Resolved | §9 Phase 1 deliverables explicit |
| Q12 (D-3 testability) | Resolved | Resolved | |
| BF-1 (BCD fixture breakage) | Required fix | PARTIAL | See TC-1 analysis |
| BF-2 (stderr_ref scope) | Found | Resolved | §4.3 explicitly addresses |
| B-New-1 (_make_stash() wider breakage) | NEW | Open | See §3 B-New-1 |
| B-New-2 (RuntimeError propagation) | NEW | Resolved | Path 3 handles it cleanly |
| B-New-3 (confidence level mis-production) | NEW | Partial | Tie-case labels "data_inferred" though alphabetic drove selection |
| B-New-4 (partial-state vs. memory invariant) | NEW | Resolved | Not a conflict; `analyzer_init_error` is out-of-band |
| B-New-5 (SQ-2 in-process vs. subprocess) | Open | Resolved | In-process is correct per memory |

### Specific change requests for APPROVE

The following two items must be clarified before implementation begins:

**CR-1 (TC-1 / B-New-1)**: v2 §7's "3 tests require update" must be revised to include one of:
- Explicit statement that `_make_stash()` at line 289-303 must also receive `scatter_feature_chain_counts`, OR
- Alternative: move the RuntimeError guard inside the `else` branch (len >= 2) only, so single-feature stashes do not trigger it

**CR-2 (TC-2 SQ-1)**: v2 §5.2 must specify whether `fallback_no_chain_data` produces a companion `feature_errors` warning entry. Per `feedback_invariant_with_fallback_hides_drift.md`, a fallback confidence level that does not surface as an active warning in a monitored field violates the memory. The designer must either: (a) add a companion `feature_errors["bonus_chain_dynamics"]` warning entry for `fallback_no_chain_data` state, or (b) explicitly justify why the `trigger_target_confidence` field alone is sufficient monitoring.

These are minor specification clarifications, not architectural changes. Implementation can begin on Clusters E and A immediately. Cluster D (specifically d2) should not begin until CR-1 and CR-2 are resolved.

---

## §10 Implementation Readiness

**Ready for impl-* Phase 1 (Cluster E)**: YES. No open issues affect Cluster E. The differential assertions, file enumeration, and inject-bug recipe are all verified correct by the validator (06 §8). Phase 1 can begin.

**Ready for impl-* Phase 2 (Cluster D)**: CONDITIONAL. D-1 (paylines sort), D-3 (unique confidence), D-4 (avg_bonus_payout None) are ready. D-2 (trigger_target chain-count) must wait for CR-1 and CR-2 resolution before impl begins.

**Ready for impl-* Phase 3 (Cluster A)**: YES. The TC-3 Region 2 test spec is fully resolved. The SQ-2 in-process inject-bug mechanism is resolved. The `_safe_write_summary_json` BF-2 import-order fix is specified. Phase 3 is independent of the D-2 CR-1/CR-2 resolution.

---

*Critique v2 end.*
