# Critique Round 2 — ticket P2-A1 Foundation files
**impl-critic** | 2026-05-18

---

## Verdict

**APPROVE-WITH-REVISIONS**

The round-2 spec alignment is genuine and complete: all 11 elements from `04_v5 §5.2` are present verbatim in `features/_base.py`. The 57 tests correctly cover the round-2 contracts. The inject-bug discipline is real (7 experiments documented, each naming the test that fires).

Three issues prevent a clean APPROVE:

1. The verifier's `04_verification.md` was written against the round-1 state and does not verify the round-2 code. This is the primary blocker.
2. `feature_protocol.py` remains after the tester has completed migration, making its "backward compat" justification hollow. It is live dead code that imports a `AnalyzerFeature` name pointing to the wrong class.
3. `compute_hash` constructs a `Path` relative to the current working directory, not relative to the project root — a silent failure in any non-root CWD context.

The remaining items are deferred-risk flags for Wave 2b/c authors, not blockers for this ticket.

---

## Chain-integrity finding — `04_verification.md` describes round-1, not round-2

The verifier's `04_verification.md` was produced for round 1. Its §1 table reads:

```
C1 - @runtime_checkable Protocol + isinstance | 7 | PASS
```

and §2 imports `fresh_slotlab.analyzer.feature_protocol` (the old Protocol path). The round-2 implementation ships `features/_base.py` (ABC), 57 tests, and a rewritten registry. The verifier ran against 37 tests on the Protocol. The verifier's PASS verdict cannot extend to round-2 code it has not seen.

The verifier's §9 "Issues for Critic" still names the Protocol-vs-ABC mismatch as a blocking issue — that is the issue the round-2 implementer fixed. This confirms the verifier artifact predates round 2.

**Impact**: the entire §3 (hash determinism), §4 (deviation summary), and §5 (broader suite 2500 passed) in `04_verification.md` are round-1 numbers. The round-2 implementer self-reports 57/57 and 2440 passed; the verifier has not independently confirmed either.

This is a required revision.

---

## Stress questions

### Q1 — `feature_protocol.py` retained: is the "backward compat" justification still valid?

**Scenario**: The implementer kept `feature_protocol.py` with the justification "backward compat while impl-tester round-2 test migration completes." The round-2 tester has completed migration: all 57 tests import from `fresh_slotlab.analyzer.features._base`, and the tester's open-gaps note (`03_tests.md`, bottom) says "feature_protocol.py (round-1 file) still exists; subprocess smoke still passes for it. It may be removed in a later cleanup ticket."

The `__init__.py` docstring marks it "Deprecated (Round 1, kept for backward compat during test migration)." The condition for removal — test migration complete — has been met.

**What the file does now**: `feature_protocol.py` exports a class named `AnalyzerFeature` (a `@runtime_checkable Protocol`) at `fresh_slotlab.analyzer.feature_protocol`. The `feature_registry.py` now imports `AnalyzerFeature` from `features._base` (the ABC). If any Wave 2b author writes `from fresh_slotlab.analyzer.feature_protocol import AnalyzerFeature` — a plausible mistake given the file is still there — they get the Protocol, not the ABC. `register()` will then reject their feature with a `TypeError: register() requires an AnalyzerFeature instance` because the Protocol class is not an ABC subclass. The error message is correct but the root cause is confusing.

**Attempted answer**: The implementer's open issue #1 says "Flag for impl-verifier to remove." The verifier's round-1 report does not mention removal. No one has removed it. The round-2 tester explicitly calls it a "cleanup ticket." This is a deferred time bomb, not a resolved item. The test migration is complete; there is no remaining justification for the file's presence.

**Verdict**: ✗ Not resolved. The condition for removal has been met. The file should be deleted in this round — not deferred to a cleanup ticket. Keeping it creates a trap for Wave 2b authors who may import the wrong `AnalyzerFeature`.

---

### Q2 — `compute_hash` CWD dependency: will it work in production subprocess context?

**Scenario**: `features/_base.py` line 215:

```python
src = Path(cls.__module__.replace(".", "/") + ".py")
```

`Path("fresh_slotlab/analyzer/features/_base.py")` is a relative path. `Path.read_bytes()` on a relative path resolves against the current working directory (`os.getcwd()`) at call time. When the analyzer's main subprocess is launched from the project root, CWD is the project root and this resolves correctly. But the spec says `compute_hash` is called by `compute_effective_analyzer_version` — which is called at report-write time inside a subprocess spawned by the batch worker.

The batch worker subprocess sets CWD explicitly? The verifier's `04_verification.md §2` shows the subprocess smoke command is run with `cwd=str(ROOT)` in the test harness. The production subprocess path is NOT verified here.

Looking at the test `test_compute_hash_matches_sha256_of_source_file` (line 501-526): the test computes `expected` via `ROOT / (module_path.replace(...) + ".py")` using the absolute `ROOT`, but the implementation uses a bare relative `Path`. The test runs with CWD set to project root (where pytest is launched), so it passes. A subprocess launched from a different directory (e.g., Windows task scheduler launching from `C:\Users\pangg\`) would produce a `FileNotFoundError`.

**Attempted answer**: The docstring on `compute_hash` says it raises `FileNotFoundError` "if the source file cannot be found." This is documented. However, the spec verbatim (`04_v5 §5.2 line 347`) says exactly `Path(cls.__module__.replace(".", "/") + ".py")` — a relative path. The spec itself has this ambiguity. The question is whether any caller will ever run `compute_hash` from a non-root CWD.

The memory `reference_sampling_api.md` shows the analyzer is called via subprocess from the backend. The backend workers use `cwd` set to the project root per `feedback_subprocess_import_suicide_and_module_globals.md`. If all callers are launched with CWD = project root, this is safe. But it is a hidden assumption.

**Verdict**: ⚠ Partial. The CWD dependency is inherited verbatim from the spec and is documented in the docstring. It is a real fragility but matches what the spec says to implement. Should be flagged for Wave 2b when `compute_feature_hashes()` is written — that function must either enforce CWD or convert to absolute paths.

---

### Q3 — `manifest=None` returns all features: is this path tested?

**Scenario**: `feature_registry.get_features_for_machine` has a documented stub behavior: when `manifest=None`, return all registered features. The implementer notes in `02_implementation.md §Contract verification row C4`:

> `manifest=None` returns all (documented stub) | PASS | Implementation + docstring; no test for stub path (correct — it's future behavior)

The tester's `03_tests.md §Open gaps` also says "Per-machine manifest loader — Phase 3 deliverable. The `manifest=None` stub behavior in `get_features_for_machine` is documented in the implementation; tests assert it returns all features in that case."

But examining `test_analyzer_foundation.py`: there is NO test that calls `get_features_for_machine("M14", manifest=None)` and asserts it returns all features. The `test_empty_registry_returns_empty_list` uses a non-None manifest `{"analyzer_features": ["feat_x"]}`. The claim in `03_tests.md` that "tests assert it returns all features in that case" is false — no such test exists in the file.

The implementer says "no test for stub path (correct — it's future behavior)" and the tester repeats this, but `03_tests.md` also says "tests assert it returns all features in that case" — these two statements contradict each other.

**Attempted answer**: The `manifest=None` code path at `feature_registry.py:144-147` is live, documented, and untested. The contradiction between the tester's two statements is a documentation error. The code itself is correct: `if manifest is None: return list(ALL_FEATURES)`. The only harm of the untested path is that a future refactor could accidentally break the `None` branch and no test would catch it.

This is not a severe gap — the `None` path is four lines and trivially correct. But the tester's claim that tests cover it is inaccurate, which is a documentation disagreement worth flagging.

**Verdict**: ⚠ Partial. The code is correct. The test coverage claim in `03_tests.md` ("tests assert it returns all features in that case") is false — no such test exists. This is a minor documentation inaccuracy, not a code defect.

---

### Q4 — `REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}`: mutable class-level default shared across all subclasses

**Scenario**: The ClassVar default is `{}` — a mutable dict defined once on the base class. In Python, class-level mutable defaults are shared across all instances of all subclasses unless the subclass explicitly overrides them. If a feature author writes:

```python
class MyFeature(AnalyzerFeature):
    FEATURE_ID = "my_feature"
    # REGISTERED_FALLBACK_RULES not overridden
    
    def extract(self, ...): ...
    def reduce(self, ...): ...
    def emit(self, ...): ...
```

and then at runtime someone does `MyFeature.REGISTERED_FALLBACK_RULES[1] = {...}` — they mutate the base class's dict, affecting every subclass that inherits the default. This is a well-known Python ClassVar footgun.

However: the intended usage is that subclasses always override `REGISTERED_FALLBACK_RULES` when they need fallback rules, and never mutate the inherited default. The docstring says "keyed by old SCHEMA_VERSION; each value is a dict mapping old field names to new field names." This implies the value is set at class definition time, not mutated at runtime. Feature authors who follow the template will override it.

**The spec verbatim** (`04_v5 §5.2 line 334`) says `REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}` — so the implementation exactly matches. The spec itself uses a mutable default.

**Attempted answer**: This is a spec-faithful implementation of a known Python footgun. The risk materializes only if someone mutates `AnalyzerFeature.REGISTERED_FALLBACK_RULES` directly rather than overriding it on a subclass. No test covers this mutation path. The docstring gives no explicit warning. Wave 2c feature authors should be told to always override, not mutate.

This is a forward-looking risk, not a current defect. The implementation correctly matches the spec.

**Verdict**: ⚠ Partial. Implementation matches spec. Risk is real but contingent on Wave 2c author behavior. Should be documented explicitly in the Wave 2c brief's "feature author pitfalls" section.

---

### Q5 — Round-2 verifier coverage: what did the verifier actually verify?

**Scenario**: The verifier's `04_verification.md` was produced for round 1. It reports:
- 37/37 PASSED (round-1 test file)
- Subprocess smoke on `feature_protocol` (round-1 module)
- Hash determinism: 3 runs of E1 = `2da53c98604d`
- Broader suite: 2500 passed (round-1 broader suite count)

The round-2 implementer reports:
- 57/57 PASSED (round-2 test file)
- Broader suite: 2440 passed (different count from verifier's 2500)

The broader suite count difference (2500 vs 2440) is unexplained. Possible causes: (a) verifier ran with a different test scope (included integration/ tests that the implementer excluded), (b) the fixture environment differs, or (c) the counts are measuring different things. This discrepancy is not addressed anywhere in the chain.

**Attempted answer**: The implementer's `02_implementation.md` says "2440 passed, 23 skipped, 1 deselected, 1 xfailed." The verifier's round-1 says "2500 passed, 23 skipped, 1 xfailed, 4 failed." The 60-test difference could be the 4 pre-existing failures that are now xfailed or the test scope (implementer ran `tests/backend/ tests/integration/ -q` per verifier's §5; same command). More likely the verifier's round-1 ran against a different test state (round-1 code + round-1 broader suite). This is unresolvable without a fresh round-2 verifier run.

**Verdict**: ✗ Not addressed. The verifier has not run against round-2 code. The 57/57 claim is self-reported by the implementer. The broader suite count discrepancy (2500 vs 2440) is unresolved. A fresh verifier run is required.

---

## Disagreements: implementer vs tester vs verifier

### Disagreement 1 — Verifier describes round-1, not round-2

The verifier `04_verification.md` reports 37 tests and references `feature_protocol` (the round-1 Protocol). The implementer and tester report 57 tests against `features/_base` (the round-2 ABC). The verifier has not verified round-2 code.

This is the most significant chain disagreement. The verifier's PASS verdict is for a different implementation than the one the tester tested.

### Disagreement 2 — Tester claims `manifest=None` path is tested; it is not

`03_tests.md §Open gaps` says "tests assert it returns all features in that case [manifest=None]." No such test exists in `test_analyzer_foundation.py`. The same document also says "Per-machine manifest loader — Phase 3 deliverable. The `manifest=None` stub behavior is documented in the implementation; no test for stub path (correct — it's future behavior)." These two statements in the same document contradict each other. The second statement is accurate; the first is not.

### Disagreement 3 — Broader suite count: 2500 (verifier round-1) vs 2440 (implementer round-2)

A 60-test count difference between verifier and implementer is unexplained. The discrepancy may be benign (different test scope between rounds) but is undocumented and unresolved.

### Disagreement 4 — `feature_protocol.py` removal status

The implementer's open issue #1 says "Flag for impl-verifier to remove." The verifier's `04_verification.md` does not mention removal. The tester says "It may be removed in a later cleanup ticket." Three parties have three different positions on a simple deletion. This is a coordination gap, not a design disagreement — but it means the file remains indefinitely unless someone acts.

---

## Hidden assumptions

1. **`compute_hash` CWD = project root.** The implementation assumes the Python process CWD is the project root when `compute_hash` is called. This holds for pytest (run from root) and for analyzer subprocesses (per codebase conventions). It breaks silently if a future caller runs from a different directory. No test covers the CWD-mismatch failure mode.

2. **`REGISTERED_FALLBACK_RULES` default dict is not mutated.** The implementation assumes Wave 2c authors will always override the ClassVar on their subclass, never mutate the inherited base-class dict. No guard or warning exists in the code. The docstring template (`Implementation template::`) shows overriding `SCHEMA_KEYS` and `RTP_CONTRIBUTION` but not `REGISTERED_FALLBACK_RULES`.

3. **No production code imports `feature_protocol.py`.** The implementation notes `feature_protocol.py` is "kept for backward compat during test migration." The assumption is that no production code has started importing it (since it was only created in round 1, a few hours ago). This is plausible but unverified — no grep of the codebase for `from fresh_slotlab.analyzer.feature_protocol import` was documented in the chain.

4. **`manifest` dict always has the `"analyzer_features"` key.** `get_features_for_machine` calls `manifest.get("analyzer_features", [])` — gracefully handles a missing key. But the function signature docstring says the manifest "Must contain an `analyzer_features` key." This creates an ambiguity: the code handles absence silently (returns empty list), but the contract says absence is a bug. No test covers the case where manifest is a non-None dict missing `"analyzer_features"`. This could mask a manifest construction bug in a Phase 3 caller.

---

## Edge cases not covered by round-2 tests

1. **`compute_hash` called from non-root CWD.** No test exercises the failure path when the working directory is not the project root. A CI environment with a non-standard CWD would fail silently (produce `FileNotFoundError`, not a hash).

2. **`register()` called with an `AnalyzerFeature` subclass where `FEATURE_ID = ""`** (the base class default). If a feature author forgets to override `FEATURE_ID`, they get `FEATURE_ID = ""`. The first such feature registers successfully. The second attempts to register with the same `FEATURE_ID = ""` — and is silently dropped. This dedup silences the programming error. No test covers the `FEATURE_ID = ""` collision scenario.

3. **`manifest` dict without `"analyzer_features"` key passed to `get_features_for_machine`.** Code handles it via `.get(..., [])` returning `[]`. The contract says it "Must contain" the key. No test asserts the silent-empty-list behavior or documents it as intended.

4. **`REGISTERED_FALLBACK_RULES` base-class dict mutation.** No test asserts that mutating `AnalyzerFeature.REGISTERED_FALLBACK_RULES` in place propagates to all inheriting subclasses (which it would). This is the test that would catch if the spec's mutable default creates shared state issues.

5. **Instantiation of `AnalyzerFeature` directly** (not subclass). The ABC prevents this with `TypeError: Can't instantiate abstract class AnalyzerFeature with abstract methods extract, reduce, emit`. A test asserting `AnalyzerFeature()` raises `TypeError` would cement this as a tested invariant. Currently no such test exists.

---

## Required revisions

**R1 (BLOCKER)**: Produce a round-2 `04_verification.md`. The verifier must run the round-2 test suite (57 tests), the round-2 subprocess smoke (importing `features._base`, not `feature_protocol`), and the round-2 broader suite. The existing `04_verification.md` describes round-1 and cannot serve as round-2 verification.

**R2 (SHOULD-FIX in this round)**: Delete `feature_protocol.py`. The tester has completed migration. The "backward compat during test migration" justification is expired. Keeping it creates a named import trap for Wave 2b authors. One-line fix: `git rm fresh_slotlab/analyzer/feature_protocol.py`. Update `__init__.py` docstring accordingly.

**R3 (SHOULD-FIX before Wave 2b)**: Add a note to `features/_base.py`'s `compute_hash` docstring (and the Wave 2b ticket brief) that `compute_feature_hashes()` must resolve paths relative to an absolute root, not use `compute_hash` directly if CWD cannot be guaranteed. Alternatively, convert `compute_hash` to use `Path(__file__).resolve().parent.parent...` chain — though that deviates from spec verbatim.

**R4 (NICE-TO-HAVE)**: Fix the tester's `03_tests.md` documentation contradiction: the statement "tests assert it returns all features in that case [manifest=None]" should be corrected to "no test covers the manifest=None stub path (future behavior)."

**R5 (NICE-TO-HAVE)**: Add a test for `FEATURE_ID = ""` double-register collision to document the silent-dedup behavior as intentional. Add a comment to `register()` noting that features with `FEATURE_ID = ""` will silently collide.

---

## Commit-message `## Self-critique` section

(Verbatim, paste-ready for the commit body when this ticket ships)

```
## Self-critique

- Q: Does the round-2 verifier cover the round-2 code (57 tests, ABC, features/_base)?
  A: NO — 04_verification.md was produced for round 1 (37 tests, Protocol, feature_protocol).
     Verifier must re-run against round-2 before ship. [OPEN — R1 blocker]

- Q: Should feature_protocol.py be deleted now that test migration is complete?
  A: YES — the "backward compat during test migration" justification expired when round-2
     tests landed. File is dead code that creates a named-import trap for Wave 2b authors.
     [OPEN — R2 should-fix]

- Q: Does compute_hash work when called from a non-root CWD?
  A: ONLY if CWD == project root. Path is relative, per spec verbatim. Production batch worker
     launches from root (per codebase conventions) so this holds today. Documented in
     docstring as FileNotFoundError risk. Wave 2b compute_feature_hashes() must enforce CWD
     or convert to absolute path. [OPEN — forward risk for Wave 2b]

- Q: Is manifest=None behavior tested?
  A: NO — 03_tests.md contradicts itself; no test calls get_features_for_machine(m, None).
     Code is correct; documentation is inaccurate. [OPEN — R4 nice-to-have]

- Q: Does REGISTERED_FALLBACK_RULES = {} create a shared-mutable-default footgun?
  A: YES — inherited by all subclasses that don't override; mutation propagates globally.
     Intended usage (override at class definition) is safe. No test guards against mutation.
     Implementation matches spec verbatim. [TRACKED — forward risk for Wave 2c]

- Q: Does FEATURE_ID = "" (base default) cause silent collision in register()?
  A: YES — two features with FEATURE_ID="" dedup silently; second registration dropped.
     Programming error masked. No test covers this. [TRACKED — nice-to-have guard]

- Q: Does the 11-element spec alignment table match 04_v5 §5.2 verbatim?
  A: YES — verified line-by-line. All 11 elements present. [CLOSED — GREEN]

- Q: Are the 57 tests testing the round-2 contracts, not round-1?
  A: YES — regression tests for NAME/applies_to/aggregate/finalize ABSENT are present.
     7 inject-bug experiments documented. [CLOSED — GREEN pending R1 verifier run]

- Q: Are there import-time side effects in any of the new files?
  A: NO — C5 subprocess tests cover all 4 new module paths. [CLOSED — GREEN]

- Q: Does the hash composition algorithm match 04_v5 §4.1 exactly?
  A: YES — unchanged from round 1; versioning.py not touched. [CLOSED — GREEN]
```

---

## Summary table

| Stress question | File:line or scenario | Verdict |
|---|---|---|
| Q1: feature_protocol.py removal — justification still valid? | `feature_protocol.py` (full file); `__init__.py:11-14` | ✗ |
| Q2: compute_hash CWD dependency in production subprocess? | `features/_base.py:215`; `test_...foundation.py:511-519` | ⚠ |
| Q3: manifest=None path — is it actually tested? | `feature_registry.py:144-147`; `03_tests.md §Open gaps` | ⚠ |
| Q4: REGISTERED_FALLBACK_RULES mutable class default shared across subclasses? | `features/_base.py:106`; `04_v5 §5.2 line 334` | ⚠ |
| Q5: Verifier covers round-2 code? | `04_verification.md §1` (37 tests) vs `03_tests.md` (57 tests) | ✗ |
