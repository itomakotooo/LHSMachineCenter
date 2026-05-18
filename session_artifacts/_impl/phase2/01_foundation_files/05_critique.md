# Critique — ticket P2-A1 Foundation files
**impl-critic** | 2026-05-18

---

## Verdict

**APPROVE-WITH-REVISIONS**

The implementation is clean, the tests are thorough, and the hash algorithm matches the spec exactly. The primary defect is a brief-vs-spec mismatch on the Protocol/ABC API surface that the ticket's own author acknowledges is an authoring error. That mismatch must be resolved before Wave 2b (core carve) can import from these files without silently building on the wrong contract. Additionally, the verifier artifact is completely absent from the chain, which is a process invariant violation.

---

## Chain-integrity finding — 04_verification.md MISSING

Per `docs/IMPL_TEAM_PROCESS.md §2` and `§3 Wave 2`, the verifier produces `04_verification.md` as a required Wave 2 artifact. That file does not exist at `session_artifacts/_impl/phase2/01_foundation_files/04_verification.md`. The critics role is to cross-check all four documents (brief, impl, tests, verification); there is no `04_verification.md` to cross-check.

The implementer's `02_implementation.md` reports "37/37 PASSED" and the tester's `03_tests.md` is labelled "sufficient," but neither of those is a substitute for the verifier's independent end-to-end run.

**Impact**: This critique is written against three of the four chain documents. Any finding that would have required verifier-level empirical evidence (cross-run hash determinism, actual subprocess rc, the broader 1204-passed suite claim) is unverified from the critic's vantage point.

This is flagged as a required revision: verifier must produce `04_verification.md` before this ticket ships.

---

## Stress questions

### Q1 — Is the brief-vs-spec deviation a production-breaking defect?

**Scenario**: Wave 2b (core carve) imports `AnalyzerFeature` from `feature_protocol.py` and writes its first real feature class. The arch spec (`04_v5 §5.2`) declares `FEATURE_ID`, `SCHEMA_KEYS`, `REQUIRES`, `RTP_CONTRIBUTION`, `REGISTERED_FALLBACK_RULES`, and `compute_hash(cls)` as the canonical members. The ticket brief (`§3 C1`) specifies `NAME`, `SCHEMA_VERSION`, `applies_to`, `aggregate`, `finalize`. The implementer shipped the brief's surface.

**Gap enumeration**:
- `FEATURE_ID` (spec) vs `NAME` (ticket + impl) — naming only, same semantics. Renaming later is a two-file search-and-replace but it means 100+ feature-class definitions across Wave 2c/d/e all use `NAME`, then must be renamed if Wave 2b decides to align to spec.
- `applies_to(self, machine_id, machines_config)` (ticket) is absent from spec — the spec has no `applies_to` method. The spec relies on the manifest's `analyzer_features` list to declare applicability. This is a semantic difference: ticket says the feature decides its own applicability at runtime; spec says the manifest decides statically. If Wave 2b/c/d features implement `applies_to` and Wave 2b's core carve implements a manifest-driven filter that ignores `applies_to`, the method silently becomes dead code.
- `aggregate/finalize` (ticket) vs `extract/reduce/emit` (spec) — three different verbs, different call-site signatures. `aggregate` takes a full `Iterable[ParsedChunk]` whereas spec's `extract` takes a single `(parse_state, chunk_dict)` pair. This is a structural difference in the call model, not just naming. A feature implementing `aggregate(self, chunks: Iterable[...], accumulator: dict)` cannot satisfy `extract(self, parse_state, chunk_dict) -> dict` without rewriting.
- `SCHEMA_KEYS: ClassVar[tuple[str, ...]]` (spec) — absent from impl. Wave 2b's manifest validation rule 2 ("every `analyzer_feature` ID MUST correspond to a class in `feature_registry.ALL_FEATURES`") and rule 8 ("every feature whose `RTP_CONTRIBUTION=True` flag is set MUST be present in the manifest's `analyzer_features`") both read ClassVar fields that don't exist yet. When Wave 2b or 2e tries to write the RTP integrity gate, it will find `RTP_CONTRIBUTION` is not on the base class and must add it, breaking the Protocol shape that the 37 tests have now locked in.
- `REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]]` (spec) — absent from impl. Per `feedback_invariant_with_fallback_hides_drift.md` this is the mechanism for exposing fallback share on a per-feature basis; its absence means the fallback-invariant variant of the verifier cannot be built until the base class is patched.
- `compute_hash(cls) -> str` (spec) — absent from impl. The hash composition algorithm in `versioning.py` takes `feature_hashes: dict[str, str]` as a parameter. Where do those hashes come from? The spec says they come from `AnalyzerFeature.compute_hash()` on each registered class. The implementer's `02_implementation.md` open issue #3 acknowledges `compute_feature_hashes()` is "out of ticket scope (Wave 2b)" but the connection between `compute_hash` on the class and `feature_hashes` dict passed to `compute_effective_analyzer_version` is not scoped anywhere in the Wave 2a or 2b tickets. If Wave 2b adds `compute_hash` as a classmethod to the ABC, Wave 2a's tests (which assert the Protocol has no `compute_hash`) will not catch any deviation.

**Attempted answer**: The two-sentence implementer note in `02_implementation.md §Protocol API surface note` says "arch-level alignment should happen before Wave 2b feature carve imports from this Protocol." This is exactly right. But the note stops there — it does not say who owns fixing it or when. The ticket §6 says "Forward dependency: this ticket is the foundation. P2-A2 (manifest loader) and Wave 2b (core carve) and Wave 2c-e (feature carve) all import from these files. **Get the contract surface right; downstream consumers depend on it.**" That sentence directly contradicts shipping with an acknowledged wrong API surface.

**Verdict**: ✗ Not addressed. The deviation is not just a naming difference — `applies_to` vs manifest-driven, `aggregate(Iterable)` vs `extract(parse_state, chunk_dict)` are structural. If Wave 2b ships against the ticket's API, aligning to spec later requires rewriting every feature class produced in Wave 2c/d/e. The cost compounds with each wave that imports from the wrong surface.

---

### Q2 — Should the implementer have stopped and escalated before completing?

**Scenario**: Per `docs/IMPL_TEAM_PROCESS.md §3 Wave 1`, "If implementer is blocked (e.g., needs arch-* clarification) → escalate to main session before Wave 2." The implementer noticed the discrepancy, documented it as "Open Issue 1," and proceeded to implement per the brief.

**Attempted answer**: The memory `feedback_dont_lower_floor_when_blocked.md` governs when to stop vs proceed. That memory is about not lowering a floor metric when blocked; it does not directly govern brief-vs-spec conflicts. However, `docs/IMPL_TEAM_PROCESS.md §5 Invariant 1` says implementers work from the brief. "Implement per brief, flag deviation" is the correct behavior for an implementer role. The escalation responsibility belongs to the main session (coordinator), not the implementer. The implementer's behavior was process-correct.

The failure point was that the brief was written with the wrong API surface (main-session-author error, acknowledged in the prompt). The implementer caught it, flagged it clearly, and completed their scope. That is the right behavior.

**Verdict**: ✓ Adequately addressed by the implementer's documentation. Responsibility for the brief error belongs to the coordinator, not to the implementer for completing it.

---

### Q3 — Do the 5 missing ClassVars block any Wave 2b/c/d/e contract?

**Scenario**: Wave 2c ships `RTPFeature` (a universal feature). The arch spec says it must have `RTP_CONTRIBUTION: ClassVar[bool] = True`. If the base class does not define `RTP_CONTRIBUTION`, the feature class can still define it — but `isinstance(f, AnalyzerFeature)` will return True regardless of whether `RTP_CONTRIBUTION` is present, because `@runtime_checkable` Protocol only checks the members declared in the Protocol definition.

Result: Wave 2e's manifest validation rule 8 ("if `console_diagnostic_complete: true`, every `RTP_CONTRIBUTION=True` feature MUST be in `analyzer_features`") reads `RTP_CONTRIBUTION` from registered feature instances. If `RTP_CONTRIBUTION` is not on the Protocol and a Wave 2c feature author omits it, the instance's `RTP_CONTRIBUTION` lookup raises `AttributeError` at validation time — not caught by the registry's `isinstance` gate, not caught by the tests that only verify the Protocol shape.

**Attempted answer**: The missing ClassVars do not break anything in Wave 2a itself (foundation layer). They break the downstream invariant enforcement. Specifically `RTP_CONTRIBUTION` is needed for manifest validation rule 8, `REGISTERED_FALLBACK_RULES` for the fallback-share invariant (per `feedback_invariant_with_fallback_hides_drift.md`), `SCHEMA_KEYS` for schema-version enforcement (rule 5), and `REQUIRES` for dependency satisfaction (rule 4). None of these are Wave 2a requirements — they are Wave 2b-e requirements. But the Protocol is the one place where "all features must have X" is enforced. If X is not on the Protocol, feature authors can omit it silently.

**Verdict**: ⚠ Partial. Missing ClassVars do not block Wave 2a itself but create a silent omission trap for Wave 2c-e feature authors. `RTP_CONTRIBUTION` specifically is the one that could cause a runtime `AttributeError` in Wave 2e's integrity gate if a feature omits it and the gate tries `f.RTP_CONTRIBUTION`.

---

### Q4 — Is `compute_hash` on the class coordinated with `versioning.py`'s `feature_hashes` parameter?

**Scenario**: `compute_effective_analyzer_version` takes `feature_hashes: dict[str, str]` as a parameter. The spec says those hashes come from calling `AnalyzerFeature.compute_hash()` on each class, which reads the class's source file via `Path(cls.__module__.replace('.', '/') + '.py').read_bytes()`. The implementer's `versioning.py` is correct for the algorithm but leaves the question of where `feature_hashes` comes from entirely open.

The spec's `compute_feature_hashes()` function is listed as a Wave 2b deliverable (open issue #3 in `02_implementation.md`). The implementer's `versioning.py` does not call or import anything from `feature_registry` to obtain those hashes. But the caller of `compute_effective_analyzer_version` will need to pass them. Who is the caller? The spec says the analyzer's versioning step calls it at report-write time. That caller must import both `versioning` and `feature_registry`, get the hash for each registered feature, and pass the dict in.

**Attempted answer**: The implementer correctly scoped `versioning.py` to the pure algorithm and left hash-collection to Wave 2b. The interface (`feature_hashes: dict[str, str]`) is the right abstraction — caller responsibility. However, `compute_hash` on the class (as the spec defines it) is what makes `feature_hashes` computable without hard-coding hashes. If `compute_hash` is never added to the base class (because the brief omits it), Wave 2b's `compute_feature_hashes()` has no standard way to compute per-feature hashes — it must either reach into source files directly (coupling) or be added as a separate utility outside the class hierarchy.

**Verdict**: ⚠ Partial. The `versioning.py` interface is clean. The connection between `compute_hash` on each feature class (spec) and `feature_hashes` dict (impl parameter) is unscoped. Wave 2b will need to design this from scratch. If Wave 2b's design differs from the spec's `compute_hash` classmethod approach, the two are uncoordinated and may produce different hashes for the same feature source file.

---

### Q5 — ABC vs Protocol: does any downstream consumer require one over the other?

**Scenario**: The spec says `AnalyzerFeature(ABC)` (requires `abstractmethod`; child classes must explicitly inherit). The ticket and impl say `@runtime_checkable Protocol` (duck-typing; no inheritance required).

**Concrete consequence of the difference**:
- ABC: a class that defines all required methods but does NOT inherit `AnalyzerFeature` will NOT be caught by the ABC machinery — it can be registered via `register()` only if `isinstance` uses duck typing. But with ABC, `isinstance` only returns True for subclasses (unless the ABC defines `__subclasshook__`). The `register()` function currently uses `isinstance(feature, AnalyzerFeature)` as the gate. Under ABC, a class that does not inherit but implements all methods would fail `isinstance` and be rejected by `register()`. Under Protocol, it passes.
- The spec's `abstractmethod` decorator enforces that abstract methods cannot be called on the base class (raises `TypeError`). Protocol has no such enforcement.
- `compute_hash(cls)` is a classmethod on the ABC. Classmethods cannot be declared in a `Protocol` in a way that is structurally checked by `@runtime_checkable`. Putting a classmethod in a Protocol definition does not make it a Protocol member for `isinstance` checking purposes.

**Downstream consumer question**: Wave 2c writes `class RTPFeature(AnalyzerFeature): ...`. Under ABC, forgetting to implement `extract` raises `TypeError` at instantiation time (excellent DX). Under Protocol, forgetting to implement `extract` is not caught until `isinstance` check at registration time (good, but only at registration, not at class definition). Either way, the `register()` gate catches missing methods before they get into `ALL_FEATURES`.

The practical difference is: with ABC, inheriting from `AnalyzerFeature` without implementing all abstract methods is a hard error at class-instantiation time, giving an earlier signal to feature authors. With Protocol, missing methods are only caught when `register()` is called.

**Attempted answer**: The ticket brief explicitly says Protocol (`@runtime_checkable`). The spec says ABC. For the foundation layer itself, the choice matters little — the registry's `isinstance` gate catches structural violations either way. For downstream DX, ABC gives better error messages. For `compute_hash`, Protocol cannot structurally check classmethods; ABC can define them abstractly.

**Verdict**: ⚠ Partial. Protocol is functional for the foundation layer. The ABC vs Protocol choice becomes load-bearing when (a) `compute_hash` needs to be enforced on subclasses and (b) Wave 2c feature authors want Python-level enforcement rather than registry-gate enforcement. This is not a blocker for Wave 2a, but it is a design debt that must be resolved before the first real feature is written.

---

### Q6 — The tester wrote 37 tests against the wrong API surface. How many survive a spec-align rewrite?

**Scenario**: If the team aligns `feature_protocol.py` to the spec (ABC, `FEATURE_ID`, `extract/reduce/emit`, 5 new ClassVars, `compute_hash`), which of the 37 tests survive unchanged?

**Test-by-test analysis**:
- C2 tests (9 tests on `compute_effective_analyzer_version`) — these are independent of the Protocol shape and test the hash algorithm directly. All 9 survive a spec-align unchanged.
- C3 tests (5 tests on `ALL_FEATURES` + `register()`) — registry behavior does not depend on the Protocol's member names. However, the `register()` function currently checks `isinstance(feature, AnalyzerFeature)`. If `AnalyzerFeature` changes to ABC (requiring inheritance), all test stubs that do NOT inherit from `AnalyzerFeature` would fail `isinstance`. The 5 C3 tests use inline stub classes that do not inherit. All 5 would need to be updated to either inherit from the new ABC or use a different registration path.
- C4 tests (4 tests on `get_features_for_machine()`) — same issue: test stubs do not inherit. Additionally, `applies_to()` would no longer be a Protocol member under spec-align (no `applies_to` in spec). The C4 tests test `applies_to` filtering — if the spec-aligned version uses manifest-driven filtering instead, these 4 tests would need to be rewritten from scratch.
- C1 tests (7 tests on `isinstance`) — these directly test the Protocol shape. Every test checks `isinstance` against a stub missing one of: `NAME`, `SCHEMA_VERSION`, `applies_to`, `aggregate`, `finalize`. Under spec-align, `NAME` → `FEATURE_ID`, `applies_to` is removed, `aggregate` → `extract`, `finalize` → `emit`. All 7 tests would need to be rewritten.
- C5 tests (5 subprocess import tests) — module-path independent. All 5 survive.
- C6 inject-bug tests (7 tests) — the C6 tests for C1 (drop aggregate → isinstance False) and C3 (dedup) would need rewriting for the same reasons as C1 and C3 above.

**Rough count**: 9 (C2) + 5 (C5) = 14 survive unchanged. 23 tests need rewriting.

**Verdict**: ✗ Not addressed. More than half the test suite tests the wrong contract. A spec-align rewrite is not a trivial patch — it is a rewrite of the Protocol definition and 23 of 37 tests. The implementer and tester would need a full second pass.

---

### Q7 — Does the `applies_to()` method create a tension with the manifest-driven architecture?

**Scenario**: The spec's architecture declares which features apply to which machine via the manifest's `analyzer_features` list (static, declarative). The ticket's `applies_to(self, machine_id, machines_config) -> bool` method makes applicability a runtime function on the feature instance (dynamic, imperative).

The stub features implement `applies_to` as machine-ID comparisons (`return machine_id == "M274"`). But in the spec's design, this check is done by reading `manifest["analyzer_features"]` and seeing if the feature's `FEATURE_ID` is in that list. The manifest is the single source of truth per `04_v5 §5.7` ("Feature discovery + missing-feature runtime error — `feature_registry.ALL_FEATURES` runtime source of truth. Manifest typo caught at validation").

If both `applies_to` (ticket) and the manifest's `analyzer_features` list (spec) exist simultaneously, they can disagree. A feature could return `applies_to(M274, ...) == True` but M274's manifest might not list the feature, or vice versa.

**Attempted answer**: The ticket's `get_features_for_machine()` uses `applies_to` as its filter. The spec's approach would use `[f for f in ALL_FEATURES if f.FEATURE_ID in manifest[machine_id]["analyzer_features"]]`. These are different filters with different sources of truth. Under the spec design, `applies_to` becomes dead code (or conflicts). The tester tested `get_features_for_machine` via `applies_to` predicates — those tests are also testing the wrong filter mechanism.

**Verdict**: ✗ Not addressed. The `applies_to` method is architecturally inconsistent with the spec's manifest-driven applicability. It's not just a naming difference; it is a different architectural decision about where applicability lives. This must be resolved before Wave 2b.

---

### Q8 — Is the `ALL_FEATURES` process-global mutable list safe under the broader test suite?

**Scenario**: `feature_registry.ALL_FEATURES` is a module-level mutable list. The implementer's `02_implementation.md` notes this and says "Tests must use the `_reset_registry` fixture (save/restore) to avoid cross-test contamination." The tester correctly added this fixture.

However, the test suite includes 1204 passing tests across the broader codebase. Any test that imports `fresh_slotlab.analyzer.feature_registry` (transitively, via another import) without using the fixture could leave state in `ALL_FEATURES` that leaks into the foundation tests.

The tester's C3 tests start with `assert len(_registry_mod.ALL_FEATURES) == 0` as a precondition. If a test earlier in the session imports and modifies the registry without resetting, this assertion fails. The fixture saves/restores the original state at test time — but "original state at test time" might already be non-empty if another test in the suite registered features before this test ran.

More concretely: `_stub_features.py` is NOT registered at import time (correct per C5). But if any Wave 2b code that lands later imports and registers features at module import time, importing that module during any other test would populate `ALL_FEATURES` and break the C3 precondition.

**Attempted answer**: The current tests are clean because nothing else imports or registers features yet. The fixture correctly saves/restores the list. The risk is forward-looking: Wave 2c features that register themselves at module import time (the spec's intended pattern per `§5.7`) will break C3's "empty on fresh import" invariant unless the fixture's save/restore approach correctly handles a non-empty baseline.

Looking at the fixture: it saves `original = list(_registry_mod.ALL_FEATURES)` and restores it after the test. If Wave 2c code registers a feature at import time and that module is imported by the test runner before C3 runs, `original` will be non-empty — and C3's `assert len == 0` will fail on the second line of `test_all_features_empty_on_fresh_import` because the fixture starts from the non-empty baseline.

**Verdict**: ⚠ Partial. The fixture is correct for the current state. The `test_all_features_empty_on_fresh_import` test will become brittle once Wave 2c adds auto-registering modules to the test environment's import path. This is a future fragility, not a current defect.

---

### Q9 — Did the verifier's subprocess smoke actually run? (Chain integrity)

**Scenario**: `04_verification.md` does not exist. The C5 tests in `03_tests.md` do spawn real subprocesses via `subprocess.run`, so the subprocess import smoke is covered by pytest. But `docs/IMPL_TEAM_PROCESS.md §5 Invariant 2` says "W2 agents read the full W1 chain." And `§3 Wave 2` says the verifier's role is to run the code independently and report `04_verification.md`.

The implementer's claim of "37/37 PASSED" is self-reported in `02_implementation.md`. The tester's "sufficient" verdict is self-reported in `03_tests.md`. Neither of these is independent empirical verification. The verifier agent was the independent validator — and that artifact is missing.

The broader suite claim ("1204 passed, 18 skipped, 1 xfailed") in `02_implementation.md` is also self-reported by the implementer. The pre-existing-failure explanations are plausible but unverified.

**Attempted answer**: The team spawned verifier and critic in parallel per §3. The critic (this document) received the chain. The verifier did not produce `04_verification.md`. This could mean the verifier was not spawned, was spawned and failed silently (per §9 failure modes: "spawn succeeds but task never notifies"), or was spawned and produced output that was lost.

**Verdict**: ✗ Not addressed. Missing verifier artifact is a process invariant violation per `docs/IMPL_TEAM_PROCESS.md §2`. The critic cannot cross-check verifier findings that do not exist. The ticket cannot ship without `04_verification.md`.

---

### Q10 — Is the implementer's hash-algorithm snapshot cross-check independent?

**Scenario**: The tester's `03_tests.md` says "Pre-computed independently via reference implementation before reading implementer's code." The reference implementation in `test_analyzer_foundation.py` (`_ref_effective_version`) is structurally identical to the implementer's `compute_effective_analyzer_version`. If both were derived from the same §4.1 pseudocode simultaneously (which they likely were), the independence claim depends on whether the tester genuinely computed the snapshot values without seeing the implementer's work.

**Examining the snapshots**: `_SNAPSHOT_E1 = "2da53c98604d"`. If we accept the §4.1 algorithm is correct (it is — the algorithm is mechanically straightforward sha256), both implementations will converge on the same values by design. The "independent" claim is somewhat vacuous here: any correct implementation of the same deterministic algorithm produces the same output. The test proves the algorithm is implemented correctly, not that it was designed independently.

The inject-bug proofs (changing `[:12]` to `[:11]`, changing dedup logic) are genuinely independent structural checks that go red on the injected bug.

**Verdict**: ✓ Adequately addressed. The snapshot independence claim is slightly overstated, but the tests correctly verify the algorithm matches §4.1, which is the actual requirement. The inject-bug proofs are valid.

---

## Disagreements: implementer vs tester vs verifier

### Disagreement 1 — Verifier vs everyone: verifier is absent

The verifier artifact (`04_verification.md`) does not exist. Per `docs/IMPL_TEAM_PROCESS.md §2`, verifier is a required W2 role. This is not a content disagreement — it is a missing party.

### Disagreement 2 — Brief §3 C1 vs 04_v5 §5.2: the contract surface disagreement

The brief specifies `NAME/SCHEMA_VERSION/applies_to/aggregate/finalize` as the Protocol.
The arch spec (`04_v5 §5.2`) specifies `FEATURE_ID/SCHEMA_KEYS/SCHEMA_VERSION/REQUIRES/RTP_CONTRIBUTION/REGISTERED_FALLBACK_RULES` + `extract/reduce/emit` + `compute_hash` classmethod.

The implementer implemented the brief's surface and flagged the discrepancy (correct behavior per role rules). The tester tested against the brief's surface (also correct — tester works from brief per `docs/IMPL_TEAM_PROCESS.md §5 Invariant 1`). The arch-critic team's approved spec (`04_v5 §5.2`) says something different.

This is a ticket-brief error, not an implementer or tester error. The main session (author of `00_ticket.md`) introduced the inconsistency between the brief and the arch spec it cites.

### Disagreement 3 — `register()` return contract inconsistency

`00_ticket.md §3 C3` says: "Returns same ALL_FEATURES reference." The implementer's `feature_registry.register()` returns `None` (no return statement). The tester's `test_register_returns_expected_reference` tests that `id(ALL_FEATURES)` is unchanged before and after `register()` — this is testing identity of the list object, not the return value. The test does not call `result = register(...)` and check `result is ALL_FEATURES`. So the tester implicitly accepted `None` as the return value while testing an adjacent property (list identity). The brief's "Returns same ALL_FEATURES reference" is satisfied by the identity test, but the literal return value is `None`, not the list reference.

This is a minor inconsistency — the brief's intent is preserved by the identity test even if the return value doesn't match the literal phrase.

---

## Hidden assumptions

1. **Wave 2b will absorb the API-surface conflict.** Both implementer and tester assume the mismatch is resolved "before Wave 2b" without specifying who resolves it. If Wave 2b proceeds by writing features against the brief's API (the only thing that exists in code), the mismatch is permanently deferred.

2. **`_stub_features.py` is test-only.** The `__init__.py` docstring lists `feature_protocol / versioning / feature_registry` as sub-modules but not `_stub_features`. The `_stub_features.py` has no guard preventing production code from importing it. A future Wave 2b author finding the file might import it, registering test stubs in production.

3. **`feature_registry.ALL_FEATURES` idempotency uses NAME, not identity.** The dedup check compares `existing.NAME == name`. Two different instances of the same feature class have the same NAME and the second registration is silently dropped. A developer who wants to re-register after a live config reload (unlikely in this codebase, but possible) has no mechanism to do so. The "double-import guard" use case is well-handled; the "upgrade registration" use case is not.

4. **The `compute_effective_analyzer_version` parameter `base_hash` is a caller responsibility.** Nothing in the Wave 2a code computes or validates `base_hash`. The function raises `ValueError` on empty string but silently accepts any non-empty string, including a hardcoded constant. A caller that passes `"placeholder"` as `base_hash` will get a deterministic but meaningless version hash. Wave 2b's `compute_base_analyzer_version()` (not yet scoped) is the intended supplier; there is no gating mechanism until that function exists.

---

## Edge cases not covered

1. **`applies_to()` raising an exception.** `get_features_for_machine` calls `f.applies_to(machine_id, machines_config)` in a list comprehension with no try/except. A buggy feature implementation that raises inside `applies_to` will propagate the exception and abort the entire query, returning nothing. No test covers this path.

2. **`machines_config=None` in tests.** Several C4 tests call `get_features_for_machine("M14", machines_config=None)`. The stubs' `applies_to` ignores `machines_config` entirely. But a real feature would access `machines_config["machines"]`. Passing `None` as `machines_config` in tests that verify filtering behavior teaches future feature authors that `None` is a valid value — it is not, it is a test artifact. No test covers what happens when a real feature's `applies_to` receives `None` and tries to access it.

3. **Registry pollution across test session (forward-looking).** As noted in Q8: once Wave 2c features auto-register at import time, the `_reset_registry` fixture's "restore to original" approach will restore to a non-empty baseline, making `test_all_features_empty_on_fresh_import` either trivially pass or intermittently fail depending on import order.

4. **`versioning.py` with a feature in `machine_features` that is NOT in `feature_hashes`.** The code does `fhash = feature_hashes[fid]` which raises `KeyError`. The docstring documents this as "programming error — register features before calling." But there is no test for this error path — no test asserts that `compute_effective_analyzer_version` raises `KeyError` when a referenced feature is missing from `feature_hashes`. This means if Wave 2b's caller passes an incomplete `feature_hashes` dict, the error message will be an opaque `KeyError('some_feature_id')` with no context about what went wrong.

5. **The `_stub_features.py` stub's `aggregate` method consumes a generator.** `UniversalStubFeature.aggregate` iterates `chunks` with `for chunk in chunks:`. The docstring on `aggregate` in `feature_protocol.py` says "do not consume a generator that callers also iterate." But the stub iterates the generator. If a test passes the same chunks generator to multiple features, the second feature sees an empty iterator. No test covers multi-feature aggregation with a single generator input.

---

## Required revisions

Per APPROVE-WITH-REVISIONS verdict:

**Revision R1 (BLOCKER — Required before ship)**: Produce `04_verification.md`. The verifier artifact is missing. Spawn `impl-verifier` to run the full chain: pytest, subprocess smoke independently, hash determinism across two separate Python processes, broader suite no-regression count.

**Revision R2 (BLOCKER — Required before Wave 2b starts)**: The main session (coordinator) must make an explicit decision on the Protocol vs ABC API surface alignment before Wave 2b's ticket is written. Options:
  - (a) Align foundation to spec: rewrite `feature_protocol.py` to ABC with `FEATURE_ID/SCHEMA_KEYS/REQUIRES/RTP_CONTRIBUTION/REGISTERED_FALLBACK_RULES/compute_hash`. Rewrite 23 of 37 tests. Rewrite the 4 stub features. Remove `applies_to` from the Protocol. This is the clean path.
  - (b) Declare the brief's API as the implementation design: write a one-paragraph ADR (architecture decision record) in `08_handoff.md` or a new `session_artifacts/_impl/phase2/01_foundation_files/ADR_protocol_vs_abc.md` explaining why `NAME/applies_to/aggregate/finalize` was chosen over the spec, and what Wave 2b-e must do instead of `applies_to`. This path freezes the brief's API as the shipped design and the arch spec becomes historical context only.
  - (c) Split the difference: keep Protocol for the type system but align member names to spec's `FEATURE_ID`/`extract`/`reduce`/`emit` while dropping the ABC-only members (`REQUIRES`, `REGISTERED_FALLBACK_RULES`, `compute_hash`) for now. This reduces the divergence to the minimum while staying within Protocol mechanics.

Which option is chosen must be an explicit documented decision, not a deferral. The current state — ship the brief's API with a note saying "fix before Wave 2b" — is not a decision; it is a deferred conflict.

**Revision R3 (SHOULD-FIX before Wave 2b)**: Add a test that `compute_effective_analyzer_version` raises `KeyError` with a useful error message when a `machine_features` entry is absent from `feature_hashes`. The current docstring says this is a programming error; add a test that makes it a tested programming error.

**Revision R4 (NICE-TO-HAVE)**: Add `__all__` to `_stub_features.py` and add a module-level comment `# TEST USE ONLY — do not import in production code` to prevent accidental production imports.

---

## Commit-message `## Self-critique` section

(Verbatim, paste-ready for the commit body when this ticket ships after revisions)

```
## Self-critique

- Q: Does the Protocol API surface match 04_v5 §5.2?
  A: NO — brief specified NAME/applies_to/aggregate/finalize; spec specifies FEATURE_ID/extract/reduce/emit + 5 ClassVars + compute_hash classmethod. Implemented per brief (correct for implementer role). Main session must decide on alignment before Wave 2b ticket is written. Open issue documented in 02_implementation.md. [OPEN — requires coordinator decision before Wave 2b]

- Q: Are the 37 tests testing the right contract?
  A: Tests correctly cover the brief's C1-C6 contracts. If spec-align happens in R2, 23/37 tests need rewriting. C2 (9 tests) and C5 (5 tests) survive any API change. [OPEN — depends on R2 decision]

- Q: Is 04_verification.md present?
  A: NO — verifier artifact is missing. Critic flagged this as R1 blocker. Chain is incomplete without it. [OPEN — must produce before ship]

- Q: Does applies_to() conflict with the manifest-driven architecture?
  A: YES — applies_to(self, machine_id, machines_config) is an instance method predicate; the spec uses the manifest's analyzer_features list as the applicability filter. Both cannot coexist as the single source of truth. Main session must resolve in R2. [OPEN — same as API surface decision]

- Q: Is the process-global ALL_FEATURES list safe under broader test suite expansion?
  A: Currently safe. Will become fragile once Wave 2c features auto-register at import time. The _reset_registry fixture restores to import-time baseline, which will be non-empty by then. Future ticket must address. [TRACKED as known fragility]

- Q: Does compute_effective_analyzer_version have a clear supplier for its base_hash and feature_hashes inputs?
  A: base_hash supplier (compute_base_analyzer_version) is Wave 2b. feature_hashes supplier (compute_feature_hashes via compute_hash classmethod) is also Wave 2b but unscoped. The connection between compute_hash on the class and the feature_hashes dict is uncoordinated between Wave 2a and Wave 2b. [OPEN — Wave 2b ticket must explicitly scope this]

- Q: Are there import-time side effects in any of the 4 new modules?
  A: No — verified by C5 subprocess tests. [CLOSED — GREEN]

- Q: Does the hash algorithm match 04_v5 §4.1 exactly?
  A: YES — algorithm verified against reference implementation, 6 snapshot values, inject-bug proof. [CLOSED — GREEN]
```

---

## Summary table

| Stress question | File:line or scenario | Verdict |
|---|---|---|
| Q1: Brief-vs-spec deviation is production-breaking? | `feature_protocol.py:44`, `04_v5 §5.2:326-348` | ✗ |
| Q2: Should implementer have escalated? | `02_implementation.md §Open issues #1` | ✓ |
| Q3: 5 missing ClassVars block Wave 2b-e? | `feature_protocol.py:70-105`, `04_v5 §5.6 rules 4/5/8` | ⚠ |
| Q4: compute_hash coordination with versioning.py? | `versioning.py:30-88`, `02_implementation.md §open issue #3` | ⚠ |
| Q5: ABC vs Protocol downstream impact? | `feature_protocol.py:43-44`, `round_win.py:102` | ⚠ |
| Q6: How many of 37 tests survive spec-align? | `test_analyzer_foundation.py` full file | ✗ |
| Q7: applies_to() vs manifest-driven architecture? | `feature_registry.py:114`, `04_v5 §5.7` | ✗ |
| Q8: ALL_FEATURES global safe under suite expansion? | `feature_registry.py:42`, `test_analyzer_foundation.py:579-591` | ⚠ |
| Q9: 04_verification.md missing — chain integrity? | (file does not exist) | ✗ |
| Q10: Hash snapshot cross-check independent? | `test_analyzer_foundation.py:104-121`, `_SNAPSHOT_E1` | ✓ |
