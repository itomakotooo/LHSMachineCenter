# Phase C6 — impl-critic critique

> **Date**: 2026-05-27
> **Branch**: `claude/analyzer-unbundle-c2`
> **Critic**: impl-critic
> **Verdict**: APPROVE-WITH-FIXES

---

## §1 Verdict

**APPROVE-WITH-FIXES**

One required fix before commit (Required Fix #1 — test comment accuracy). One optional improvement. No code logic defects found. Gap #3 and #8 closures are correctly implemented. F6 inline defensive keep is acceptable per trade-off documented in plugin docstring. All 3 inject-bug cycles confirm critical paths are guarded.

---

## §2 Required fixes before commit/merge

**Required Fix #1 — test_c3_5_isolation_m275_only.py comment accuracy (MISLEADING but tests still PASS)**

The coordinator updated `_NON_M275_EFFECTIVE_VERSION` from `47ff60ffa3f4` to `6aae41144cea` (correct for C6 state). However the comment at line 98 still reads:

```
#   C5 ship:   6aae41144cea (add upstream_feature_breakdown + collect_mechanic = 7 plugins)
```

This is **factually wrong after C6**. Verified:
- C5 7-plugin non-M275 hash: `47ff60ffa3f4`
- C6 8-plugin non-M275 hash (with bonus_chain_dynamics): `6aae41144cea`

The variable `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` is the C6 value, not the C5 value. The comment at line 98 attributes it to C5 with 7 plugins, which is incorrect. The docstring at lines 6-7 also says "M14 effective_version UNCHANGED at 6aae41144cea" — but M14's effective_version DID change from C5 to C6 (47ff60ffa3f4 → 6aae41144cea); it's "current" not "unchanged."

The test PASSES because the value matches reality. The COMMENT is wrong and will mislead any future developer reading version history.

**Required update**: Update comment at line 98 from `C5 ship` to `C6 ship`, change the plugin count to `8 plugins`, add `bonus_chain_dynamics` to the list. Update docstring lines 6-7 to clarify this is the current C6 value, not "unchanged from C5". Update the variable comment at line 94 `# C5 effective_version for non-M275 machines` to `# C6 effective_version for non-M275 machines`.

This is required before commit to avoid cementing a false historical record in the test. Future phase would inherit a misleading version history table.

---

## §3 Q1 — F6 inline KEPT (pure stash+overwrite pattern correctness)

Verdict: **ACCEPTABLE TRADE-OFF, adequately documented.**

The plugin docstring at line 50-64 documents the rationale precisely:
- (a) C4 invariant assert at line 4980 checks `"bonus_chain_dynamics" in summary["player_impact"]` — if inline were deleted, this assert fires before emit loop, crashing M275 runs.
- (b) `machine_mechanics.emit()` reads `bonus_chain_dynamics` during its own emit call — if inline were deleted and machine_mechanics runs before bonus_chain_dynamics in topo sort, it reads a missing key.

The stash is written AFTER the inline (line 4862-4868, PIA diff context), so the plugin emit() is guaranteed to receive a pre-built value. The overwrite at `player_impact["bonus_chain_dynamics"] = bcd` is the same dict object (same value, same reference path). Confirmed byte-identical by the test suite.

**Perf concern**: Effectively computes bonus_chain_dynamics twice — once inline (builds the dict), once in plugin (reads + re-assigns same dict). Not a concern: no computation in plugin, pure dict passthrough at O(1) reference assignment. 10 concurrent planners: each runs a separate subprocess; no shared state. Not a concern.

**True risk**: If a future phase deletes the F6 inline to "clean up" without also updating the C4 invariant assert and the machine_mechanics.emit() ordering contract, it will break. The trade-off is: current state is redundant but safe. The docstring flags this clearly. No action needed now.

---

## §4 Q2 — trigger_target alphabetical-first heuristic correctness

Verdict: **KNOWN LIMITATION, honestly documented, no better generic heuristic available without domain knowledge.**

The brief (§2.2) explicitly acknowledges the M275 case: `by_feature` has `["NewFreespin", "NormalCollectionSpin"]`. Plugin picks `NewFreespin` (alphabetically first). The byte_identical_results.md confirms this (`pid 666 trigger_target = "NewFreespin"`). The test at `test_c6_gap_3_pid_666_trigger_marker.py:151-162` explicitly asserts `trigger_target == "NewFreespin"`.

**The theoretical bug raised by the coordinator prompt**: "if features are `['FreespinChain', 'Banana']`, alphabetical picks 'Banana' which is WRONG."

This is a genuine risk for future machines with multiple scatter-trigger features that alphabetically don't sort to the semantically correct one. However:
1. M275 is the only machine with this data as of C6.
2. The brief §2.2 explicitly labeled this as an implementer concern with "conservative" framing.
3. `trigger_target_confidence = "data_inferred"` signals downstream consumers that this is not a guaranteed match.
4. No ground truth signal exists to pick the "correct" feature without manifest annotation (Tier 1 override).

The correct fix would be a manifest `mechanism_overrides.scatter_trigger_target` field. That is Tier 1 territory and out of C6 scope. The confidence level serves as the advisory signal. **Flag as known limitation, no C6 action needed.**

The docstring at line 41-43 documents this as "conservative — most machines have a single scatter-triggered bonus feature," which is accurate.

---

## §5 Q3 — trigger_target_confidence="data_inferred" semantic clarity

Verdict: **ADEQUATE for current use. "unique" confidence level documented but never emitted — minor inconsistency.**

The plugin docstring (line 29) says: `"data_inferred" when trigger_target is set from chain-dynamics data`. The `emit()` at line 208 only emits `"data_inferred"` regardless of whether `scatter_feature_names` has 1 or 2+ features. The docstring algorithm (line 39-43) describes a case 2 with "exactly one feature" and case 3 with "multiple features" — but BOTH emit `"data_inferred"` with no distinction.

The test at `_VALID_CONFIDENCE_VALUES = {"data_inferred", "unique", "unknown"}` (line 52, test_c6_gap_3_pid_666_trigger_marker.py) admits `"unique"` as valid, but the plugin never emits `"unique"`. This is a dead branch in the spec — the docstring mentions it as an option but code doesn't implement it.

**Risk**: An operator reading `trigger_target_confidence="data_inferred"` on a single-feature machine doesn't know if this was a 1:1 match (high confidence) or an N:1 pick (lower confidence). This semantic gap matters if operators route on confidence level for manual review prioritization.

This is a documentation mismatch between spec and impl. Not a runtime bug since the test's `_VALID_CONFIDENCE_VALUES` admits both values and the test for the specific M275 case asserts `"data_inferred"` directly (line 451-453).

**Action**: Optional improvement — either implement "unique" for len(scatter_feature_names)==1 case, or remove "unique" from docstring and test valid set. Not blocking for C6 commit.

---

## §6 Q4 — gap #8 Option B spec compliance

Verdict: **SPEC-COMPLIANT per brief §2.4.**

Brief §2.4 explicitly states: "Option B is cleaner since payout_ids_top20 is already aggregate. Implementer choice." The implementer chose Option B (notes only, not shape/cols/paylines). This is a deliberate design decision supported by the brief.

The gap #8 original description in brief says "payout_ids_top20 缺 shape / cols / paylines / 备注." Option B closes the 备注 (notes) part only. The brief's Option B justification (per-(pid,ST) fields don't collapse cleanly to per-pid aggregate) is technically sound. Gap #8 is closed as "notes present" per the acceptance criteria §4, item 3-4.

No spec deviation.

---

## §7 Q5 — 253 manifest re-serialization format fidelity

Verdict: **FORMAT PRESERVED. No regression.**

Spot-checked M1.json diff:
- Indentation: 2 spaces (preserved)
- Field ordering: preserved (Python json.dump with sort_keys=False, maintaining original order)
- Only change: comma after `"collect_mechanic"` and new line `"bonus_chain_dynamics"`
- No trailing newline added (consistent with original format — `\ No newline at end of file` absent in diff)

Spot-checked M14.json: identical pattern.

The diff shows clean `+  "bonus_chain_dynamics"` insertion with correct comma on prior line. No extraneous whitespace changes, no field reordering. Format is intact.

---

## §8 Q6 — 5-site registration completeness

Verdict: **5 SITES CONFIRMED.**

Verified from byte_identical_results.md and diff:
1. PIA package-mode import block (`fresh_slotlab/player_impact_analyzer.py` line ~4897, confirmed in diff)
2. PIA script-mode import block (line ~4926, confirmed in diff)
3. versioning.py package-mode import (line ~173, confirmed in diff)
4. versioning.py script-mode import (line ~184, confirmed in diff)
5. `bonus_chain_dynamics.py` module-level `register()` call (line 246, confirmed in plugin source)

validate_manifests.py is site 6 (import at line ~52, confirmed in diff). Brief §2.6 counted validate_manifests as part of "5-site" registration — the count depends on whether validate_manifests is numbered separately or folded into the "5 import sites." Either way: all sites that need the registration have it.

---

## §9 Q7 — topo sort complexity and cyclic risk

Verdict: **NO RISK.**

`REQUIRES = ()` on BonusChainDynamics means it has no declared ordering dependency. Topo sort over 9 nodes all with REQUIRES=() is O(N) linear pass. No cycle possible with zero edges. The sort order for zero-REQUIRES nodes is implementation-defined but deterministic. Stash pattern intentionally avoids REQUIRES dependency on the inline F6 block — correct choice since inline F6 is not a plugin.

---

## §10 Q8 — is_trigger_marker detection edge cases

Verdict: **LOGIC IS CORRECT. One edge case documented but not tested.**

The detection logic (mechanism_registry.py line 147-153):
```python
for pid_s, win in payout_id_win.items():
    if win == 0.0 and not pid_has_regular_line.get(pid_s, False):
        _scatter_set.add(pid_s)
```

This correctly handles:
- **pid with line_id=-1 in some rounds, regular lines in others (mixed)**: `pid_has_regular_line[pid]` is True if ANY record has line_id != -1 (built by payouts_by_spin_type.extract()). Mixed pids are NOT classified as scatter markers. This is correct — a pid that sometimes triggers scatter AND sometimes pays regular wins is not a pure scatter trigger.
- **pid with all win=0 AND line_id=-1 (M275 pid 666 case)**: `win==0 AND not pid_has_regular_line[pid]` → classified as scatter. Correct.
- **pid with line_id=-1 but win>0 (theoretical edge)**: `win > 0` → condition fails → NOT classified as scatter. Correct. A pid that has both scatter-only records AND non-zero win is not a pure scatter trigger marker.

**Untested edge case**: a machine where `payout_id_win` is populated but `pid_has_regular_line` dict is completely absent for that pid (key not in dict at all). The `.get(pid_s, False)` handles this with False default — classifies as scatter if win==0 AND key absent. This is correct behavior (if no regular line record was ever seen, it can't be a regular pay pid).

**The genuine edge case not covered by tests**: a machine where pid has win=0 in the observed sample but non-zero wins in a different sample (statistical accident). In 10k+ spins this is unlikely but possible for rare high-win pids. This is a known limitation of tier-3 raw detection. No test covers it because it's a probabilistic risk, not a logic bug. Tier 1 manifest override exists as the escape valve.

---

## §11 Q9 — base_hash unchanged verification

Verdict: **CONFIRMED UNCHANGED.**

`git diff HEAD -- fresh_slotlab/analyzer/core/` returns empty (no output). Bash confirmed zero output.

`compute_base_analyzer_version()` returns `fa440e3eb5f6` as verified in both `test_c6_byte_identical_bonus_chain.py::TestBaseHashUnchangedC6::test_base_hash_value` and `test_c6_carve_completion.py::TestCarveCompletionPreconditions::test_base_hash_unchanged`.

**Additionally verified**: M275 effective_version WITH all 9 plugins is `5c78f3834a1e`; M14 effective_version WITH all 8 plugins is `6aae41144cea`. Both verified by direct hash computation.

---

## §12 Q10 — 3rd-time hardcoded value churn (test design smell)

**This is a structural test debt finding that must be called out explicitly.**

The C3.5 isolation test (`test_c3_5_isolation_m275_only.py`) hardcodes 12-character hex version hashes as string literals (`_M275_C3_5_EFFECTIVE_VERSION`, `_NON_M275_EFFECTIVE_VERSION`). These have been updated 3 times in this C-phase carve:
- C5 commit: `47ff60ffa3f4` → `6aae41144cea` (non-M275) and `a4d1fa45cf36` → `5c78f3834a1e` (M275)
- C6 commit (this carve): same values re-updated by coordinator

Each update is a mechanical translation with NO design judgment needed — the value is literally `compute_effective_version_for_machine(machine_id, mode)`. The test SHOULD call this function directly and compare against `!= previous_phase_hash` or use a cross-machine inequality (`m275 != m14`) instead of an absolute value assertion.

**Why this pattern fails**: the version comment says "C5 ship: 6aae41144cea (7 plugins)" but the actual value is now the C6 value with 8 plugins. The test passes but the comment is wrong. Future developers reading this will be confused about what the "C5 value" actually was. This compounds each phase.

**Concrete fix design** (not required for C6 commit, but carry forward):
```python
# Instead of: assert ev == "6aae41144cea"
# Use: 
m14_ev = compute_effective_version("M14", 1)
m275_ev = compute_effective_version("M275", 1)
assert m14_ev != m275_ev, "isolation invariant: M275-only plugins must create version divergence"
assert m14_ev == compute_effective_version("M37", 1), "M14/M37 must share version"
```

The test does already have `test_m14_does_not_equal_m275_effective_version()` — that's the GOOD test. The absolute-value assertions are the ones that require manual update each phase.

**Block/defer decision**: Do not block C6 commit on this. Required Fix #1 (comment accuracy) addresses the most misleading part. The structural fix is a separate refactor task.

---

## §13 Q11 — carve completion meta test comprehensiveness

Verdict: **ADEQUATE FOR M275 DRIVING CASE. Known limitation: mode 2/5/7 untested.**

`test_c6_carve_completion.py` runs a single M275 mode 1 subprocess and asserts all 8 gaps. This is comprehensive for the driving case. Known gaps:

1. **Mode 2/5/7**: No cached chunks exist for these modes (per `user_testing_machine.md` memory: all validation walks M14 mode 1). Gap closure is only verified on mode 1. If mode 2/5/7 had mode-specific manifest overrides that excluded bonus_chain_dynamics, gap #3 and #8 would not be tested there. Currently all mode overrides are identical (universal rollout) but there is no test asserting mode isolation.

2. **No M37/M272 carve completion test**: These are representative of the BCM machines that are not M275. They have bonus_chain_dynamics in manifest (253 universal rollout) but no subprocess test verifies their payout_ids_top20 has notes. A false-positive test for M37 (expected: no trigger markers since M37 has no known scatter-trigger pid) would add confidence.

3. **Feature_errors test is the correct guard against vacuous pass**: `TestCarveCompletionPreconditions::test_no_feature_errors_m275` correctly gates all gap assertions — if any plugin throws, feature_errors is populated and the gap assertions may vacuously pass. This guard is present and correct.

Neither of these gaps blocks C6 commit — the brief's acceptance criteria §4 covers M14 and M275 explicitly. Flagged as optional carry-forward improvements.

---

## §14 Q12 — commit message facts and self-critique section

The commit message MUST include:

**Claims to assert as facts**:
1. All 8 C-phase gaps closed: #1 jackpot (C4) / #2 freespin (C4) / #3 scatter_trigger_marker (C6) / #4 multiplier_wild (C3.5) / #5 group noise filter (C5) / #6 chunk_spin_times_recommendation (C5) / #7 payouts_by_spin_type shape/cols/paylines/notes (C3) / #8 payout_ids_top20 notes (C6)
2. bonus_chain_dynamics plugin: Pattern B stash, SCHEMA_VERSION=1, REQUIRES=(), 253 universal rollout
3. F6 inline KEPT (defensive): C4 invariant assert + machine_mechanics.emit() ordering contract require it; stash overwrite is byte-identical
4. base_hash UNCHANGED: `fa440e3eb5f6` — parser/core not touched across all 6 C-phases
5. 9 plugins registered in ALL_FEATURES post-C6
6. 5-site registration: PIA×2 + versioning.py×2 + module-level register()
7. 3 inject-bug RED→GREEN: stash-skip (A) / trigger-detection-remove (B) / manifest-remove (C)
8. Test debt pattern: C3.5 isolation test hardcoded version values updated 3 times; comment accuracy fix required
9. 624 total analyzer tests pass; 81 new C6 tests

**Self-critique section must include**:
- "trigger_target alphabetical-first is a conservative heuristic with no better generic alternative" (documented)
- "C3.5 isolation test comment accuracy: `_NON_M275_EFFECTIVE_VERSION` is now the C6 value, not C5 — comment says 'C5 ship: 7 plugins' but this is the C6 8-plugin hash. Tests pass but comment is wrong. Fix comment before commit."
- "Hardcoded version string pattern in isolation tests is a recurring test debt; dynamic comparison would eliminate update burden"
- "Mode 2/5/7 gap closure not tested (no cached chunks); M275 mode 1 only"
- "reports/M14/mode_1/index.json and latest.json should NOT be committed — these are runtime-generated artifacts, not source files. Including them in a feature commit pollutes diff with test run artifacts."

---

## §15 Beyond-prompted findings

### FINDING B1: reports/M14/mode_1/index.json and latest.json in the staged diff

`git status --short` shows `M reports/M14/mode_1/index.json` and `M reports/M14/mode_1/latest.json` as modified staged files. The diff shows these files gained 4 new report version entries from subprocess test runs during C6 verification.

**These files are runtime-generated artifacts, not source code.** They track version history of generated reports — they should NOT be committed alongside a feature commit. Their presence in the diff:
1. Pollutes the feature commit with test run artifacts
2. Embeds absolute Windows paths (`C:\\Users\\pangg\\Documents\\Projects\\LHS\\...`) that are non-portable
3. Makes the diff unreadable for code review (48 lines of JSON noise vs 30 lines of actual code change)
4. Will cause conflicts if another developer runs the same tests on their machine

**This is a clear error in staging.** These files should be in `.gitignore` or explicitly unstaged before the C6 commit. This is the most actionable finding beyond the stress questions.

### FINDING B2: "unique" confidence level is a dead branch

The docstring algorithm (line 39-41) describes case 2 with exactly-one-feature → `"unique"` confidence. The test `_VALID_CONFIDENCE_VALUES` at line 52 admits `"unique"`. But the actual `emit()` code only emits `"data_inferred"` for all scatter-marker cases regardless of feature count. The `"unique"` level is never emitted.

This creates a documentation-code divergence that could lead a future plugin consumer to write handling code for `"unique"` that never triggers. It's a specification ghost — harmless now but will confuse future developers. Either implement it or remove it from spec.

### FINDING B3: payout_ids_top20 may not always be populated (defensive path at line 221)

```python
pid_rows: list[dict[str, Any]] = player_impact.get("payout_ids_top20") or []
```

If `payout_ids_top20` is absent or empty, the notes augmentation silently produces zero notes. The C4 invariant assert at line 4974 only checks that `"payout_ids_top20" IN summary["player_impact"]` — not that it's non-empty. A machine where `payout_ids_top20 = []` would produce gap #8 vacuously satisfied (no rows, no missing notes).

`test_c6_m14_no_false_trigger_markers.py::test_payout_ids_top20_nonempty` explicitly tests M14 is non-empty. But the carve_completion test does: `assert rows, "payout_ids_top20 must be non-empty for M275."` This guard is correct for M275. The risk is for the 252 other machines with universal rollout — no test verifies they have non-empty payout_ids_top20 before gap #8 is declared satisfied for them. This is a fleet-wide assumption, not a tested invariant.

---

## §16 Summary of findings

### Code-level bugs/risks

- NONE (logic is correct)

### Test-level gaps

- T1: C3.5 isolation test comment inaccuracy (Required Fix #1)
- T2: "unique" confidence level is a dead test branch (Optional — FINDING B2)
- T3: Mode 2/5/7 gap closure untested (acceptable scope limitation)
- T4: Fleet-wide payout_ids_top20 non-empty assumption untested (Q11/FINDING B3)

### Claim-vs-reality gaps (commit message vs diff)

- Coordinator/tester claim "5 pre-existing failures (C3.5 stale hardcoded values) now 624 pass" — VERIFIED TRUE. The update correctly reflects C6 state.
- Tester claim "test_m14_effective_version_unchanged" — PASSES because the value happens to be the correct C6 hash. The test NAME says "unchanged" but M14's version DID change from C5 to C6 (47ff60ffa3f4 → 6aae41144cea). The test is factually correct at commit time but misleadingly named.

### Memory feedback violations

- `feedback_no_silent_swallow.md`: NOT violated. `emit()` raises RuntimeError on missing stash (line 182-187). Post-hook failures are surfaced. No silent swallow found.
- `feedback_adversarial_self_review.md`: Not directly applicable to plugin carve, but the Self-critique section MUST be present in commit message per this feedback.
- `feedback_invariant_with_fallback_hides_drift.md`: HONORED. `is_trigger_marker` is an explicit positive signal; `trigger_target_confidence` absent for non-trigger rows.
- `feedback_no_hardcode.md`: HONORED. No machine-specific pid values; inference from mechanism_registry.
- `feedback_no_parallel_panel_impl.md`: HONORED. Notes shape mirrors payouts_by_spin_type.

---

## §17 Final verdict

**APPROVE-WITH-FIXES**

### Required fixes before commit (1)

1. **Fix test comment accuracy in `test_c3_5_isolation_m275_only.py`**: Update the comment at line 98 from `C5 ship: 6aae41144cea (add upstream_feature_breakdown + collect_mechanic = 7 plugins)` to `C6 ship: 6aae41144cea (add bonus_chain_dynamics = 8 plugins)`. Update variable comment at line 94 from `# C5 effective_version for non-M275 machines` to `# C6 effective_version for non-M275 machines`. Update docstring lines 6-7 to clarify this is the current C6 value, not "unchanged from C5" — M14's effective_version DID change from C5 to C6.

2. **Unstage `reports/M14/mode_1/index.json` and `reports/M14/mode_1/latest.json`** from the commit. These are runtime-generated artifacts with embedded absolute machine-specific paths. Including them in a feature commit is wrong.

### Optional improvements (3)

1. Implement `trigger_target_confidence = "unique"` for `len(scatter_feature_names) == 1` case, or remove "unique" from docstring and test `_VALID_CONFIDENCE_VALUES`.
2. Add dynamic version comparison to `test_c3_5_isolation_m275_only.py` to replace hardcoded hex strings with cross-machine inequality assertions.
3. Add subprocess test for at least one non-M275 BCM machine (e.g. M272) to verify notes are added to payout_ids_top20 with no false-positive trigger markers.

### What does NOT block commit

- F6 inline KEPT: documented trade-off, correct behavior
- trigger_target alphabetical-first: documented limitation, confidence label signals advisory nature
- Mode 2/5/7 untested: per project constraint (no cached chunks per memory/user_testing_machine.md)
- Test debt pattern: identified, flagged as carry-forward
