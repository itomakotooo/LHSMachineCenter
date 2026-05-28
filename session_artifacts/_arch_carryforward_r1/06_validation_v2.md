# 06 — Validation v2: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Role**: arch-validator (W3 v2)
> **Input artifacts**: `04_architecture_proposal_v2.md` (v2), `06_validation.md` (v1 with B1+B2),
>   `04_architecture_proposal.md` (v1 for delta comparison)
> **Output**: `session_artifacts/_arch_carryforward_r1/06_validation_v2.md`
> **Method**: Re-walk v1 breaks B1+B2 against v2 fix spec; re-walk all 8 v1 cases against
>   v2 changes; walk 2 new cases (Phase 2/3 ordering risk + Region 2 inject feasibility);
>   run real commands against code and test files.

---

## §0 Commands Run (v2)

All findings are grounded in real command output.

**Test file reads (confirmed line numbers and assertions):**
```
tests/analyzer/test_c6_gap_3_pid_666_trigger_marker.py:
  Line 151: def test_pid_666_trigger_target_is_new_freespin
  Line 160: assert notes.get("trigger_target") == "NewFreespin"   <- B1 confirmed

tests/analyzer/test_c6_bonus_chain_dynamics_plugin.py:
  Line 289-303: _make_stash() returns stash with scatter_feature_names = ["NormalCollectionSpin"]
                (1-element list when applicable=True)
  Line 414-435: test_emit_trigger_target_from_scatter_feature_names
                  stash = {"scatter_feature_names": ["ZFeature", "AFeature"]}  <- 2 features
                  NO scatter_feature_chain_counts in fixture
  Line 437-454: test_emit_trigger_target_confidence_data_inferred
                  stash = self._make_stash()  <- 1-element scatter_feature_names
  All other _make_stash() usages: 1-element scatter_feature_names
```

**PIA DECLARED_DEPS vs emit() error path distinction (confirmed at pia:5072-5091):**
```
for _feature in _sorted_features:
    for _dep_key in _feature.DECLARED_DEPS:      # 5073-5076
        if _dep_key not in summary:
            raise RuntimeError(...)              # 5077 -- OUTSIDE try/except
    try:
        _feature.emit(...)                       # 5081
    except Exception as _emit_exc:               # 5083 -- catches emit() raises
        summary["feature_errors"][fid] = str()   # 5091 -- goes to disk
```

**BCD plugin DECLARED_DEPS check (confirmed):**
```
fresh_slotlab/analyzer/features/bonus_chain_dynamics.py:150-151:
  DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
  REQUIRES:      ClassVar[tuple[str, ...]] = ()
```
BCD has empty DECLARED_DEPS. The scatter_feature_chain_counts key is checked
INSIDE emit(), not via DECLARED_DEPS. This distinction is critical for Part C.

**feature_registry structure (confirmed):**
```
fresh_slotlab/analyzer/feature_registry.py:63:
  ALL_FEATURES: list[AnalyzerFeature] = []  # module-level global
  register() appends to ALL_FEATURES
  get_features_for_machine() filters by manifest's analyzer_features list
```

**2+ feature stash fixtures in BCD test (grep result):**
```
Only line 418: "scatter_feature_names": ["ZFeature", "AFeature"]  <- 2 entries
All other stash fixtures use _make_stash() which has 1 entry (NormalCollectionSpin)
```

---

## §1 Part A — Re-walk B1 and B2

### B1: `test_c6_gap_3_pid_666_trigger_marker.py:160`

**v1 finding**: Assertion `== "NewFreespin"` will turn RED after D-2.
v1 §7 incorrectly said "no change needed for this test."

**v2 fix in §7 (test update 1 of 3)**:
```
Required change: update assertion to == "NormalCollectionSpin".
Also rename the test method from test_pid_666_trigger_target_is_new_freespin
to test_pid_666_trigger_target_is_normal_collection_spin.
```

**Verification against actual code**:
- Line 151 confirms the method name `test_pid_666_trigger_target_is_new_freespin`
- Line 160 confirms assertion `== "NewFreespin"`
- v2 §7 update 1 of 3 specifies BOTH the assertion change AND the method rename
- The `trigger_target_confidence` assertion in the same test file (asserting `"data_inferred"`)
  is correctly noted as unchanged (M275 has 2 features, stays in `data_inferred` path)

**Verdict: B1 RESOLVED.** v2 §7 update 1 of 3 is complete and correct. Both the assertion
value change and the method rename are specified with exact file:line.

---

### B2: `test_c6_bonus_chain_dynamics_plugin.py:432`

**v1 finding**: Fixture at line 414-419 has unsorted `["ZFeature","AFeature"]` and no
`scatter_feature_chain_counts`. After D-2 with the old silent-fallback (`or {}`),
`max()` over tied-zero counts returns `"ZFeature"` (first in unsorted list), failing
assertion `== "AFeature"`.

**v2 fix in §7 (test update 2 of 3)** specifies:
1. Add `"scatter_feature_chain_counts": {"AFeature": 100, "ZFeature": 1}` to fixture
2. Sort `scatter_feature_names` to `["AFeature", "ZFeature"]` (matching PIA behavior)
3. Assertion `== "AFeature"` stays correct (higher chain count 100 > 1 wins)

**Additional v2 change (Fix 2 in §0 revision log)**: v2 §5.2 changes the missing-key
behavior from silent `or {}` to explicit `RuntimeError`. With the RuntimeError spec,
calling emit() without `scatter_feature_chain_counts` in a 2-feature stash raises
RuntimeError, not returning `"ZFeature"`. This makes B2 fail differently (RuntimeError
propagated in test, not AssertionError) but the fix direction is the same: add
`scatter_feature_chain_counts` to the fixture.

**v2 §7 test update 2 of 3 is complete**: specifies both the fixture addition and the
reason ("AFeature wins by chain count (100 > 1), not alphabetically").

**Test update 3 of 3 clarification (BF-1 scope)**: v2 §7 update 3 correctly says to
inspect lines 437-453 to confirm whether they also lack `scatter_feature_chain_counts`.

Real code check: line 437 `test_emit_trigger_target_confidence_data_inferred` uses
`self._make_stash()`. `_make_stash(applicable=True)` returns stash with
`scatter_feature_names = ["NormalCollectionSpin"]` — a 1-element list. After D-2,
`len(scatter_feature_names) == 1` fires the `"unique"` branch, which does NOT check
`scatter_feature_chain_counts`. No RuntimeError. This test is NOT broken.

v2 §7 update 3 is correctly specified as a conditional verification step ("If absent,
add it... The impl team must inspect lines 437-453 to confirm"). The impl team will
find this test is safe. The instruction is accurate and appropriately cautious.

Grep of all 2+ feature stash fixtures: only line 418 has `["ZFeature","AFeature"]`.
All other stash fixtures use `_make_stash()` with 1 feature. Scope of update 3 is
correctly bounded.

**Verdict: B2 RESOLVED.** v2 §7 update 2 of 3 is complete and correct. The fixture
addition, the sort requirement, and the assertion rationale are all specified.
Update 3 of 3 scope is correctly stated as conditional verification; actual impact is
confined to line 414-435 test only.

---

## §2 Part B — Re-walk All 8 v1 Cases Under v2

For each case: does v2 (with §7 expansion + d2 RuntimeError + Region 2 test) still
produce correct outcome?

### Case 1: M275 (driving case)

**v2 changes affecting M275**:
- D-2 RuntimeError on missing stash key: in production, stash extension (pia:4862)
  is in the same Cluster D commit as the plugin change. Stash always has the key.
  RuntimeError never fires in production.
- d2 chain-count majority vote: NCS=841 > NF=67 → `"NormalCollectionSpin"` (correct)
- d3 unique branch: M275 has 2 features → `len >= 2` → `"data_inferred"` (unchanged)
- Region 2 test: new test for DECLARED_DEPS miss — M275 has no DECLARED_DEPS plugins;
  success path unchanged; 14 `"analyzer_init_error" not in summary` assertions remain GREEN
- 3-level confidence: M275 gets `"data_inferred"` (len=2, non-zero counts)
  No behavioral change from v1 proposal for M275 production output.

**Verdict: pass** (unchanged from v1 case 1)

---

### Case 2: M272 (BCM_FREESPIN, same d2 pattern)

No v2-specific changes affect M272. Same analysis as v1: chain-count majority vote
picks NCS (554) over NF (41) → correct. No DECLARED_DEPS; no Region 2 risk.

**Verdict: pass** (unchanged from v1 case 2)

---

### Case 3: M14 (vanilla baseline)

v2 adds `"region"` field to `analyzer_init_error` schema. M14 success path never
writes `analyzer_init_error`. The 14 test assertions `"analyzer_init_error" not in summary`
remain GREEN. No other v2 changes affect M14.

**Verdict: pass** (unchanged from v1 case 3)

---

### Case 4: M37 (single-payline classic)

No v2-specific changes affect M37. All D fixes inapplicable. Success path unchanged.

**Verdict: pass** (unchanged from v1 case 4)

---

### Case 5: M11 (jackpot_ids via raw field)

No v2-specific changes affect M11. All D fixes inapplicable. Success path unchanged.
The `"analyzer_init_error" not in summary` assertion in `test_c4_m11_jackpot_ids_union.py:133`
remains GREEN.

**Verdict: pass** (unchanged from v1 case 5)

---

### Case 6: Hypothetical 50-payline machine (d1 real case)

No v2-specific changes affect d1. The defensive ValueError pre-validation spec (§5.1)
is a v2 addition, but it is a non-breaking addition: it adds a `RuntimeError` before
the sort call for non-integer payline_id strings. For the 50-payline machine (all IDs
are integer strings), this validation always passes. No behavioral change for normal
machines.

The payline_id pre-validation would fire only for a hypothetical future machine with
non-numeric payline IDs, catching it as a `feature_errors` entry (via the emit-error
handler at pia:5083) rather than a cryptic `ValueError`. This is correct per
`feedback_capture_drift.md`.

**Verdict: pass** (unchanged from v1 case 6; d1 defensive validation is additive and correct)

---

### Case 7: Hypothetical single-scatter-feature machine (d3)

v2 changes: the `"unique"` branch in d3 is now part of the 3-level confidence spec
in §5.2. The code sketch is unchanged from v1 for the unique branch path.

Single-feature machine: `len(scatter_feature_names) == 1` → unique branch fires, no
`scatter_feature_chain_counts` needed, `trigger_target_confidence = "unique"`. Correct.

The RuntimeError on missing stash key only fires when `len >= 2 AND key absent`. For
the single-feature case, RuntimeError is never triggered. No behavioral risk introduced
by v2 Fix 2 for this case.

**Verdict: pass** (unchanged from v1 case 7; RuntimeError does not affect len=1 path)

---

### Case 8: Cluster E test migration walk

No v2-specific changes affect Cluster E. The differential assertion approach
(E-3), base_hash pin preservation, and inject-bug recipe are all unchanged.

The v2 revision log marks the revision log sections §3, §6, §8, §9, §10 as "carried
verbatim from v1." Cluster E design is in §3 (verbatim). No changes.

**Verdict: pass** (unchanged from v1 case 8)

---

### v2-specific case: Region 2 error schema

v2 adds `"region"` field to `analyzer_init_error` schema. This is a new field in the
error dict — not a backward-compat concern (0 production readers of `analyzer_init_error`,
14 test sites only check the key is ABSENT on success path). The new `region` field
is additive. No existing test breaks.

The Region 2 test spec (§4.4) asserts `analyzer_init_error["region"] == 2`, which
requires the `region` field to be present. This is a new GREEN test requirement,
not an existing test that turns RED.

**Verdict: no new cases broken by Region 2 schema addition**

---

## §3 Part C — New Case 9: Phase 2 in Isolation (Cluster D shipped, Cluster A not shipped)

**Setup**: Phase 2 (Cluster D) ships. Phase 3 (Cluster A) has NOT shipped yet.
This means v1 PIA control flow is still in effect for error paths. The DECLARED_DEPS
check at pia:5077 raises `RuntimeError` uncaught (not converted to
`PluginDeclaredDepMissingError`, no `_safe_write_summary_json` call, no region=2 key).

**The two distinct RuntimeError sources after D-2**:

**Source 1: DECLARED_DEPS RuntimeError at pia:5077 (UNCAUGHT, existing bug)**

This fires if a plugin declares `DECLARED_DEPS = ("some_key",)` and `"some_key"` is
absent from summary. In current codebase, BCD has `DECLARED_DEPS = ()`. No plugin
currently fires this path. Cluster A is the fix for this path. With D shipped and A
not shipped, this path remains uncaught — but it also remains unfired, because no
plugin has non-empty DECLARED_DEPS in the current codebase that would be missing.

**Source 2: D-2 RuntimeError inside BCD emit() (CAUGHT by pia:5083)**

v2 §5.2 specifies: if `scatter_feature_names` is non-empty and
`"scatter_feature_chain_counts"` is absent from stash, BCD emit() raises RuntimeError
with a descriptive message. This RuntimeError is raised INSIDE `emit()` at line 5081.
It is caught by `except Exception` at pia:5083.

Trace of pia:5083 path (existing, no Cluster A change needed):
```
except Exception as _emit_exc:
    print(f"ERROR: feature '{_feature.FEATURE_ID}' emit() failed: ...", file=sys.stderr)
    summary["feature_errors"][_feature.FEATURE_ID] = str(_emit_exc)
```
Then `write_summary_json` at pia:5210 runs (rc=0). The error is on disk.

**Verdict on Part C**: The D-2 RuntimeError (for missing stash key) goes through the
EXISTING emit-error handler at pia:5083, NOT through the DECLARED_DEPS path at
pia:5077. Cluster A is NOT required for D-2 to be correctly error-surfaced.

In normal production operation: stash extension at pia:4862 is in the SAME Cluster D
commit as the BCD plugin change. The stash always has `scatter_feature_chain_counts`
after D ships. The D-2 RuntimeError never fires in production when D is deployed
correctly.

If only the plugin changed but the stash extension was not deployed (partial deploy,
which is a deployment error not a design flaw): RuntimeError fires inside emit() →
caught by 5083 → `feature_errors["bonus_chain_dynamics"]` written to disk → operator
sees clear error message. Not silent. feedback_no_silent_swallow is satisfied.

**The question asked: "D-2 RuntimeError → existing PIA `except Exception` (the C2
outer guard) → silent swallow → analyzer continues with wrong output?"**

Answer: NO. The emit-error handler at pia:5083 does NOT silently swallow. It:
1. Prints the error to stderr
2. Writes the error to `summary["feature_errors"][fid]`
3. Continues the run (rc=0)
4. `feature_errors` is written to disk at pia:5210

This is the CORRECT graceful-degradation path per feedback_no_silent_swallow.md.
The outcome is persisted to disk. The analyzer does NOT continue with wrong output —
it continues with the BCD plugin output absent (and `feature_errors` entry present).

**Phase 2/3 ordering risk verdict: NO RISK.** D can ship before A without D-2
RuntimeError causing silent swallow or wrong output. The ordering constraint
(E → D → A) is preserved for the DECLARED_DEPS uncaught path (which is the Cluster A
concern), but D-2 RuntimeError does not depend on Cluster A for correct error surfacing.

---

## §4 Part D — New Case 10: Region 2 Inject-Bug Feasibility (SQ-2)

**Question**: Can the Region 2 test inject a DECLARED_DEPS miss in-process (via
monkeypatch) or does it require subprocess mode?

### PIA plugin discovery mechanism (confirmed from code)

```python
# feature_registry.py:63
ALL_FEATURES: list[AnalyzerFeature] = []  # module-level global

# feature_registry.py:77
def register(feature: AnalyzerFeature) -> None:
    ALL_FEATURES.append(feature)  # idempotent by FEATURE_ID

# player_impact_analyzer.py:5037
_machine_features = _get_features_for_machine(...)
# _get_features_for_machine filters ALL_FEATURES by manifest's analyzer_features list
```

### In-process inject feasibility

To inject a plugin with `DECLARED_DEPS = ("nonexistent_stash_key_xyz",)`:

1. Create a test plugin class in the test file (no new .py file needed):
   ```python
   class _InjectedPlugin(AnalyzerFeature):
       FEATURE_ID = "_test_region2_plugin"
       DECLARED_DEPS = ("nonexistent_stash_key_xyz",)
       REQUIRES = ()
       def emit(self, accs, summary, ctx): pass
   ```

2. Use `monkeypatch.setattr` on `feature_registry.ALL_FEATURES`:
   ```python
   # monkeypatch saves and restores the list automatically
   new_features = list(feature_registry.ALL_FEATURES) + [_InjectedPlugin()]
   monkeypatch.setattr(feature_registry, "ALL_FEATURES", new_features)
   ```

3. Create a temp manifest dict that includes `"_test_region2_plugin"` in
   `analyzer_features`.

4. Call PIA main() programmatically (or call only the emit loop section) with
   the temp manifest.

5. After test: monkeypatch restores `ALL_FEATURES` automatically.

**Risk assessment against `feedback_subprocess_import_suicide_and_module_globals.md`**:

The memory constraint says: "module global → grep every path, change self._xxx".
The risk is unintended module-global state leakage. However, pytest `monkeypatch`
is specifically designed to restore module globals after each test. `monkeypatch.setattr`
saves the original and restores on teardown. This is the approved pattern for
testing code that reads module globals.

The import-suicide risk is different: it fires when a module import triggers
side effects (like `app = build_virtual_app()` at module top). `feature_registry.py`
module import does NOT trigger side effects — `ALL_FEATURES = []` is a simple
assignment. Importing it is safe.

**In-process inject: FEASIBLE.** Recommended for test speed (no subprocess spawn,
no temp file I/O).

### Subprocess inject feasibility

Alternative: write a temp plugin .py file, set `PYTHONPATH` to include its directory,
spawn PIA as subprocess with a temp manifest JSON.

This is also feasible but adds complexity: file creation, PYTHONPATH manipulation,
subprocess spawning. The `feedback_integration_test_argv.md` memory says "stub_popen.cmds
argv" level tests are needed for sampling pipeline changes — but for a plugin injection
test, in-process is cleaner and equally valid.

### Recommendation for impl-tester

**Use in-process inject with `monkeypatch.setattr(feature_registry, "ALL_FEATURES", ...)`.**

The recipe:
1. Import `feature_registry` in the test file
2. Define the injected plugin class inline (no file needed)
3. `monkeypatch.setattr(feature_registry, "ALL_FEATURES", new_list_with_injected_plugin)`
4. Create a temp manifest dict with the injected plugin's FEATURE_ID in `analyzer_features`
5. Call the relevant PIA section (or full PIA in-process) with the temp manifest
6. Assert rc=1 via `SystemExit` capture, JSON exists, `analyzer_init_error["region"] == 2`
7. monkeypatch auto-restores `ALL_FEATURES`

The inject-bug recipe (to verify the test catches the pre-fix state): monkeypatch the
DECLARED_DEPS check to be skipped (simulating pre-fix where pia:5077 doesn't fire).
Assert that `player_impact_summary.json` does NOT exist → RED. Restore → GREEN.

**SQ-2 verdict: In-process is recommended and feasible. Subprocess is available as
fallback if PIA main() has global import side effects that interfere.**

---

## §5 Additional Finding: SQ-1 Assessment

**SQ-1**: Should `"fallback_no_chain_data"` confidence level ALSO write a
`feature_errors` companion entry?

v2 §12 asks Wave 3 to assess this. Assessment:

The `"fallback_no_chain_data"` state means: stash key IS present, but all chain counts
are zero. The run produces `trigger_target = <alphabetical-first>` and
`trigger_target_confidence = "fallback_no_chain_data"`. No RuntimeError, rc=0.

The `trigger_target_confidence` field IS written to disk (it's in the summary JSON).
`feedback_no_silent_swallow.md` says "persist diagnostic to disk." The confidence
field IS the diagnostic. It is on disk.

However, an operator scanning for issues looks first at `feature_errors`. If
`feature_errors` is absent, the operator may not notice `trigger_target_confidence`
is degraded without specifically looking at the BCD output. This is an operator-UX
concern, not a contract violation.

**Verdict**: The confidence field alone satisfies `feedback_no_silent_swallow.md`
(outcome persisted to disk). A companion `feature_errors` warning would improve
operator discoverability but is not required by the memory constraint. This is
flagged as a **minor open design question** (not a blocking break) for the designer
to decide. The impl team should implement whichever the designer specifies; either
is correct from an invariant standpoint.

This does not block APPROVE.

---

## §6 Hash Composition Trace (v2 additions only)

v1 §4 covered the full hash trace for all 8 cases. v2 introduces no new plugin files
and no new hash composition changes. The only relevant v2 change:

**`player_impact_analyzer.py` (Cluster A Region 2 + region field in schema)**:
- PIA is not a plugin file. `effective_analyzer_version` does not hash PIA bytes.
- The `"region"` field addition to `analyzer_init_error` schema is inside PIA control
  flow (error path only). No `effective_analyzer_version` change.
- `analyzer_version` (legacy) flips for 393 machines when PIA is touched. This is
  the lower blast radius option (already documented in v1 §5.4 for d4).

Hash trace remains fully correct from v1 §4. No new hash composition issues introduced
by v2 revisions.

---

## §7 Backward-Compat Check (v2 additions)

v1 §5 covered backward-compat. v2 changes add:

**`"region"` field in `analyzer_init_error` schema**: Additive. 0 production readers.
14 test sites check key ABSENT on success path (unchanged). No backward-compat impact.

**D-2 RuntimeError on missing stash key**: Only fires when stash key is absent
(deployment error or partial deploy). Normal production runs have the key present
(same commit for plugin and stash extension). No backward-compat impact.

**D-2 `fallback_no_chain_data` confidence level**: Applies only when all chain counts
are zero. 0 current machines have this state (both M275 and M272 have non-zero counts).
No existing report affected.

**Region 2 test (new test file)**: Additive. No existing test turns RED.

**Overall backward-compat**: Unchanged from v1 assessment — partial (32+37 machines
need regen for correct display; no service disruption; no consumer crashes).

---

## §8 Verdict

### Per-break verdicts

| Break | v1 finding | v2 fix | Resolution |
|---|---|---|---|
| B1 (gap_3 test:160 `== "NewFreespin"`) | Missing from v1 §7 update list | v2 §7 update 1 of 3: change to `== "NormalCollectionSpin"` + method rename | RESOLVED |
| B2 (BCD test:432 unsorted fixture + missing chain_counts) | v1 flagged but underspecified | v2 §7 update 2 of 3: add chain_counts + sort fixture + keep assertion "AFeature" wins by count | RESOLVED |

### Part C: Phase 2/3 ordering risk

D-2 RuntimeError (for missing `scatter_feature_chain_counts` stash key) fires inside
`emit()`, caught by existing pia:5083 `except Exception` handler → `feature_errors`
written to disk → no silent swallow. Cluster A is NOT required for D-2 to be correctly
surfaced. Phase 2 (D) can ship before Phase 3 (A) without ordering risk for the D-2
case. The ordering constraint E → D → A is preserved for its original reason (DECLARED_DEPS
uncaught RuntimeError at pia:5077 being the Cluster A concern), not for the D-2 case.

**Phase 2/3 ordering risk: NOT A RISK.** D-2 uses the existing graceful emit-error path.

### Part D: Region 2 inject-bug feasibility

In-process inject via `monkeypatch.setattr(feature_registry, "ALL_FEATURES", ...)` is
feasible and recommended. The `feature_registry.ALL_FEATURES` module global is safely
patchable — its import causes no side effects. The inject pattern satisfies
`feedback_subprocess_import_suicide_and_module_globals.md` when monkeypatch is used
for save/restore.

**Region 2 inject: FEASIBLE in-process.**

### Per-case v2 verdicts

| Case | v1 verdict | v2 verdict | Notes |
|---|---|---|---|
| 1 — M275 | pass | pass | D-2 RuntimeError never fires in production (stash extension in same commit) |
| 2 — M272 | pass | pass | No v2 changes affect M272 |
| 3 — M14 | pass | pass | Region field added to schema but M14 is success-path only |
| 4 — M37 | pass | pass | No v2 changes affect M37 |
| 5 — M11 | pass | pass | No v2 changes affect M11 |
| 6 — Hyp 50-payline | pass | pass | d1 defensive ValueError validation is additive and correct |
| 7 — Hyp single-scatter | pass | pass | len=1 branch unaffected by RuntimeError spec |
| 8 — Cluster E migration | pass | pass | No v2 changes to Cluster E |
| 9 — Phase 2 in isolation (new) | n/a | SAFE | D-2 RuntimeError uses existing emit-error path |
| 10 — Region 2 inject feasibility (new) | n/a | FEASIBLE | monkeypatch.setattr in-process recommended |

### Overall verdict: APPROVE

All 2 original breaks (B1 + B2) are resolved in v2 with correct and complete
specifications. The Phase 2/3 ordering risk is not a real risk — D-2 RuntimeError
is handled by the existing pia:5083 emit-error path without Cluster A. Region 2
inject-bug is feasible in-process. No new breaks found.

One open design question (SQ-1: fallback_no_chain_data companion feature_errors
warning) is flagged as a minor design decision for the designer, not a blocking concern.
The confidence field alone satisfies `feedback_no_silent_swallow.md`.

**APPROVE. Ready for impl-* team.**

---

## §9 Impl-Team Action Items (Summary)

From this v2 validation, the following items are confirmed required for the impl team:

**Phase 1 (Cluster E)**:
- 2 test files to migrate (confirmed: not 5+)
- 6 no-change files confirmed (4 base_hash + 2 dynamic/comment-only)

**Phase 2 (Cluster D)**:
- 3 test updates REQUIRED (all in same Cluster D commit):
  1. `test_c6_gap_3_pid_666_trigger_marker.py:160`: `"NewFreespin"` → `"NormalCollectionSpin"` + rename method
  2. `test_c6_bonus_chain_dynamics_plugin.py:414-419` fixture: add `scatter_feature_chain_counts` + sort list
  3. `test_c6_bonus_chain_dynamics_plugin.py:437-453`: inspect — likely no change needed (1-feature stash uses unique branch; no chain_counts required)
- Grep ALL stash fixtures with `len(scatter_feature_names) >= 2` lacking `scatter_feature_chain_counts` — currently only line 418
- Stash extension at pia:4862 MUST be in the same commit as bonus_chain_dynamics.py change

**Phase 3 (Cluster A)**:
- Region 2 test: use in-process inject with `monkeypatch.setattr(feature_registry, "ALL_FEATURES", ...)`
- `"region"` field required in both Region 1 and Region 2 `analyzer_init_error` dicts
- Region 2 partial-emit output preserved (keep + annotate, not clear)
- SQ-1 design decision needed before impl: companion `feature_errors` warning for `fallback_no_chain_data`?

---

*Validation v2 complete. 8 original cases re-walked + 2 new cases (9 + 10) walked.
Both B1 and B2 resolved. Phase 2/3 ordering safe. Region 2 inject feasible in-process.
Overall verdict: APPROVE.*
