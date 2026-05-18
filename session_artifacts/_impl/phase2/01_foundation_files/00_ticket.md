# Ticket P2-A1 — Foundation files: AnalyzerFeature Protocol + versioning + feature_registry

> Phase 2 / Wave 2a. **FIRST Phase 2 ticket.** Establishes the contract surface that all subsequent feature/carve work imports from.

---

## §1 Ticket scope

Create the framework files for the plugin-style analyzer architecture per `04_v5 §5.2` + `§4.1`. No behavior change for production (existing analyzer continues to run unchanged); this ticket just lays the import surface that Wave 2b+ work fills in.

Files expected to change (new):
- `fresh_slotlab/analyzer/__init__.py` — package marker
- `fresh_slotlab/analyzer/feature_protocol.py` — `AnalyzerFeature` `@runtime_checkable` Protocol
- `fresh_slotlab/analyzer/versioning.py` — `compute_effective_analyzer_version(machine, mode) -> str`
- `fresh_slotlab/analyzer/feature_registry.py` — `ALL_FEATURES: list[AnalyzerFeature]` + `register(feature)` helper + `get_features_for_machine(machine_id, machines_config)` query
- `tests/backend/test_analyzer_foundation.py` — regression tests per §3

---

## §2 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.2` — AnalyzerFeature Protocol full definition + worked example
- `session_artifacts/_arch/04_architecture_proposal_v5.md §4.1` — hash composition algorithm for effective_analyzer_version
- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverables 7+8` — versioning.py + feature_registry.py listed
- `session_artifacts/_arch/07_decision_v5.md P1` — per-(machine, mode) `layer4_applicable` resolution (informs versioning.py mode param)
- `session_artifacts/_arch/08_handoff.md §4 Phase 2` — Phase 2 deliverables overview
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — new modules must have no import-time side effects

---

## §3 Contract (testable invariants) — **ROUND 2 SPEC-ALIGNED (main session R2 correction)**

Round 1 brief deviated from `04_v5 §5.2` spec. Round 2 re-anchors to spec verbatim. Algorithm + tests for `versioning.py` (C2-C6) unchanged — they were correct.

### C1 — AnalyzerFeature ABC shape (per `04_v5 §5.2` verbatim)
File: `fresh_slotlab/analyzer/features/_base.py` (in `features/` subpackage; NOT `feature_protocol.py`)

`AnalyzerFeature` is an **ABC** (`from abc import ABC, abstractmethod`) — not a Protocol. Class spec:

```python
class AnalyzerFeature(ABC):
    FEATURE_ID: ClassVar[str] = ""
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    @abstractmethod
    def extract(self, parse_state, chunk_dict) -> dict: ...

    @abstractmethod
    def reduce(self, prev_acc, this_acc) -> Any: ...

    @abstractmethod
    def emit(self, final_acc, summary: dict) -> None: ...

    @classmethod
    def compute_hash(cls) -> str:
        src = Path(cls.__module__.replace(".", "/") + ".py")
        return hashlib.sha256(src.read_bytes()).hexdigest()[:12]
```

Test: subclass that implements all 3 abstractmethods + sets FEATURE_ID can instantiate; subclass missing an abstractmethod raises TypeError at instantiation. `compute_hash()` returns 12-char hex of the subclass module's source bytes.

**Applicability semantic** (changed from round 1): the brief's runtime `applies_to` predicate is REPLACED by the declarative `manifest.analyzer_features` list per `04_v5 §5.5.2`. `get_features_for_machine(machine_id, manifest)` reads the manifest's `analyzer_features` list and returns the feature instances whose `FEATURE_ID` is named there. No instance-method predicate.

### C2 — `compute_effective_analyzer_version(machine, mode)` deterministic + composable
Function signature: `def compute_effective_analyzer_version(machine: str, mode: int, *, base_hash: str | None = None, feature_hashes: list[str] | None = None) -> str`.
- Returns 12-char hex string (sha256 truncated)
- Algorithm: `sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12]` per `04_v5 §4.1`
- Deterministic: same input → same output across runs
- Composition: changing one feature's hash changes ONLY machines using that feature

Test: 3-5 worked examples per `04_v5 §4.3` (adding feature X, base_hash change, mode change) — assert each produces expected hash.

### C3 — feature_registry empty by default + register() works
`feature_registry.ALL_FEATURES` is initially `[]`. `register(feature)` appends. Returns same `ALL_FEATURES` reference. Idempotent registration of same feature (by NAME) is a no-op (or raises clear error — implementer's choice; document).

Test: empty initial state; register stub; assert length 1; register again; assert idempotent.

### C4 — `get_features_for_machine(machine_id, machines_config)` filters
Iterates `ALL_FEATURES`, returns `[f for f in ALL_FEATURES if f.applies_to(machine_id, machines_config)]`. Stable order (registration order).

Test: register 3 stubs with different `applies_to` predicates; query for a machine; assert correct subset returned in order.

### C5 — No import-time side effects per memory
`python -c "import fresh_slotlab.analyzer; import fresh_slotlab.analyzer.feature_protocol; import fresh_slotlab.analyzer.versioning; import fresh_slotlab.analyzer.feature_registry; print('OK')"` returns silently with rc=0.

Per memory `feedback_subprocess_import_suicide_and_module_globals.md`: no module-top `app = build_app()`-like patterns; no I/O at import time.

### C6 — Inject-bug TDD
Tester proves regression tests catch:
- Edit Protocol to drop one method → `isinstance` check goes False (C1)
- Edit `compute_effective_analyzer_version` to use truncated `[:11]` → length assertion fires (C2)
- Edit `register` to silently dedup by NAME → idempotency test catches via length check (C3)

---

## §4 Out of scope

- Actual carving of features from PIA into the registry (Wave 2c-e work)
- Carving core/ files (Wave 2b work)
- RTP integrity gate (Wave 2e work)
- Per-machine manifests (Phase 3 work)
- Backward compat with existing `analyzer.main()` (existing analyzer runs unchanged; this ticket only adds new framework files)

---

## §5 Rollback path

Single commit. `git revert <sha>` removes the 4 new module files + 1 test file. No existing code depends on them yet (Wave 2b+ will).

---

## §6 Risk + rollback notes

**Risk class**: LOW. New files only; no existing code modified. Stub features for smoke tests don't ship to production.

**Forward dependency**: this ticket is the foundation. P2-A2 (manifest loader) and Wave 2b (core carve) and Wave 2c-e (feature carve) all import from these files. Get the contract surface right; downstream consumers depend on it.

**Per memory `feedback_subprocess_import_suicide_and_module_globals.md`**: subprocess import safety mandatory. Verifier runs subprocess smoke per C5.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — 4 module files per §3 C1-C5; 4 stub features for smoke tests
- `impl-tester` — `tests/backend/test_analyzer_foundation.py` per §3 contracts + inject-bug per C6

### Wave 2 (parallel)
- `impl-verifier` — subprocess import smoke; pytest full suite no regression; verify hash determinism across 2 separate runs
- `impl-critic` — Protocol API surface review (are method signatures right?); hash composition algorithm review (matches `04_v5 §4.1` exactly?); naming conventions

Expected wall time: ~45-60 min (small standalone framework).
