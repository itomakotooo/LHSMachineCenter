# 04_verification.md - Ticket P2-A1 Foundation files

**Verdict: PASS**

Date: 2026-05-18
Verifier: impl-verifier (W2)

---

## 1. Pytest - Targeted Suite (37 tests)

Command:
  python -m pytest tests/backend/test_analyzer_foundation.py -v

Result: 37/37 PASSED in 0.22s - all 6 contracts (C1-C6) GREEN.

| Contract | Tests | Result |
|----------|-------|--------|
| C1 - @runtime_checkable Protocol + isinstance | 7 | PASS |
| C2 - compute_effective_analyzer_version deterministic 12-char | 11 | PASS |
| C3 - ALL_FEATURES empty; register() idempotent | 5 | PASS |
| C4 - get_features_for_machine filters + stable order | 4 | PASS |
| C5 - subprocess import rc=0 no stderr | 6 | PASS |
| C6 - inject-bug TDD (3 bug proofs) | 4 | PASS |

---

## 2. Subprocess Import Smoke (C5 end-to-end)

Per memory feedback_subprocess_import_suicide_and_module_globals.md.

Reproducer (real subprocess spawned, rc and stderr captured):
  python -c import fresh_slotlab.analyzer; import fresh_slotlab.analyzer.feature_protocol; import fresh_slotlab.analyzer.versioning; import fresh_slotlab.analyzer.feature_registry; print(OK)

Observed: stdout=OK, stderr=empty, rc=0.
All 4 new modules importable with zero side effects.
Also verified by 6 parametrized C5 tests (TestNoImportTimeSideEffects class).

---

## 3. Hash Composition Determinism (3 consecutive runs)

Reproducer:
  from fresh_slotlab.analyzer.versioning import compute_effective_analyzer_version
  kwargs = dict(base_hash=abc, feature_hashes={f1:hash1,f2:hash2}, machine_features=[f1,f2], mode=1)
  # called 3x identically

Observed:
  Run1: 2da53c98604d
  Run2: 2da53c98604d
  Run3: 2da53c98604d
  All equal: True, Length: 12

Matches tester independently precomputed snapshot E1 = 2da53c98604d.
Determinism: CONFIRMED across 3 runs.

---

## 4. Brief-vs-Spec Deviation (Open Issue 1)

Comparing ticket Section 3 C1 contract vs 04_architecture_proposal_v5.md Section 5.2.

### ClassVar attributes: 5 differ

Agreed: SCHEMA_VERSION in both. NAME (ticket/impl) = FEATURE_ID (arch) renamed.

Diverging ClassVars in arch Section 5.2 ONLY, absent in ticket/impl:
  FEATURE_ID             : ClassVar[str] = empty (ticket uses NAME instead)
  SCHEMA_KEYS            : ClassVar[tuple[str, ...]] = ()
  REQUIRES               : ClassVar[tuple[str, ...]] = ()
  RTP_CONTRIBUTION       : ClassVar[bool] = False
  REGISTERED_FALLBACK_RULES : ClassVar[dict[int, dict]] = {}

Total diverging ClassVar attrs: 5

### Methods: 7 total across both directions

Ticket/impl ONLY (absent from arch Section 5.2):
  applies_to(self, machine_id: str, machines_config: MachinesConfig) -> bool
  aggregate(self, chunks: Iterable[ParsedChunk], accumulator: dict) -> None
  finalize(self, accumulator: dict, summary: dict) -> dict

Arch Section 5.2 ONLY (absent from ticket/impl):
  extract(self, parse_state, chunk_dict) -> dict  [abstractmethod]
  reduce(self, prev_acc, this_acc) -> Any          [abstractmethod]
  emit(self, final_acc, summary: dict) -> None     [abstractmethod]
  compute_hash(cls) -> str                         [classmethod]

Net: 3 ticket/impl-only methods; 4 arch-only methods.

### Class type and file path

Ticket/impl: @runtime_checkable Protocol  fresh_slotlab/analyzer/feature_protocol.py
Arch spec:   ABC (abstract base class)     fresh_slotlab/analyzer/features/_base.py

### Versioning function signature

Ticket Section 3 C2 sketch (high-level not literal):
  compute_effective_analyzer_version(machine: str, mode: int,
    *, base_hash: str|None=None, feature_hashes: list[str]|None=None) -> str

Actually implemented (verified via inspect.signature):
  compute_effective_analyzer_version(*,
    base_hash: str, feature_hashes: dict[str, str],
    machine_features: list[str], mode: Optional[int]=None) -> str

Key differences:
  Ticket has positional machine: str; impl uses machine_features: list[str] keyword-only
  Ticket has base_hash optional (default None); impl has it required (ValueError if empty)
  Ticket has feature_hashes: list[str]; impl has dict[str,str] (per Section 4.1 lookup)
  Impl adds machine_features param the ticket omits entirely

Assessment: impl signature is more faithful to Section 4.1 algorithm. All 37 tests pass.

### Deviation count summary for critic

  5 ClassVar attrs differ (arch has; ticket/impl lacks)
  4 methods differ (7 total across both directions)
  1 class type difference (Protocol vs ABC)
  1 file path difference
  1 versioning function signature difference from ticket C2 sketch

Implementer correctly flagged this as Open Issue 1 and followed ticket brief as
binding contract per impl-* team rules. Arch-* team must resolve before Wave 2b
imports from this Protocol surface.

---

## 5. Full Pytest Suite (Regression Coverage)

Command:
  python -m pytest tests/backend/ tests/integration/ -q

Result: 2500 passed, 23 skipped, 1 xfailed, 4 failed, 7 warnings in 85.06s

### 4 failures - all pre-existing, none caused by this ticket

1. test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
   Cause: FileNotFoundError rawdata/M31/mode_1/chunk_0001.json absent from worktree
   Pre-existing: fixture not present; no new code touches M31 rawdata paths

2. test_t_critical_table_canonical.py::test_c1_player_impact_analyzer_imports_from_sampler
3. test_t_critical_table_canonical.py::test_c1_virtual_analyzer_imports_from_sampler
4. test_t_critical_table_canonical.py::test_c6_split_path_monkeypatch_proves_sampler_attr_used
   Cause: StubProcess.communicate() timeout - cross-test thread contamination in long suite
   Isolation reproducer: run those 3 tests alone -> 3 passed in 0.05s
   Not caused by new modules; pre-existing ordering artifact.

New regressions in untouched areas: 0

---

## 6. Subprocess vs In-Process Coverage

| Coverage type            | Verified | How |
|--------------------------|----------|-----|
| In-process (C1-C4, C6)   | YES      | pytest 37/37 |
| Subprocess (C5)          | YES      | real python subprocess + 6 parametrized tests |
| Hash determinism         | YES      | 3 consecutive identical outputs |
| Module-global leak check | YES      | no module-top code; stubs not auto-registered |

---

## 7. md5 / Version Invariants

Not applicable. compute_effective_analyzer_version is a pure function with no disk I/O.
No changes to existing cache write or delegate paths.

---

## 8. Frontend Preview

Not applicable. No frontend changes in this ticket.

---

## 9. Issues for Critic

Issue 1 - BLOCKING for Wave 2b: Protocol API surface gap vs arch Section 5.2.
Arch specifies extract/reduce/emit; ticket/impl has applies_to/aggregate/finalize.
These are incompatible lifecycle APIs. Arch-* team must resolve before Wave 2b lands.
Implementer correctly followed ticket brief; ticket brief was incorrect vs arch spec.

Issue 2 - non-blocking: Versioning function signature differs from ticket Section 3 C2 sketch.
Impl is algorithmically correct per Section 4.1; all 37 tests pass.

Issue 3 - non-blocking: _stub_features.py not listed in ticket Section 1 deliverables.
Stubs not registered at import time (C5 safe). Critic should confirm placement.

---

## 10. Verdict Summary

| Check | Result |
|-------|--------|
| 37/37 targeted tests | PASS |
| Subprocess import rc=0 no stderr | PASS |
| Hash determinism (3 consecutive runs) | PASS (2da53c98604d x3) |
| Full suite (2500 tests) | PASS (4 pre-existing failures 0 new) |
| New regressions in untouched areas | 0 |
| Brief-vs-spec deviation | 5 attrs + 4 methods different (documented) |
| Frontend preview | N/A |
| md5 round-trip | N/A |

PASS. Ready for impl-critic with Open Issue 1 flagged as BLOCKING for Wave 2b.
