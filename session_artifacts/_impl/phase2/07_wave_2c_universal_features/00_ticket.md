# Ticket P2-C — Wave 2c: 4 universal features (batched)

> Phase 2 Wave 2c. 4 tickets (P2-C1..C4) batched into ONE commit because all
> 4 touch `pia.main()` and parallel impl would conflict.

---

## §1 Ticket scope

Create 4 `AnalyzerFeature` subclasses, register them at module-import time,
and wire `main()` to invoke them via the registry. The 4 features
correspond to existing summary keys; backward compatibility on the summary
schema is non-negotiable.

| Feature ID                    | Module path                                                  | Existing summary key                |
|-------------------------------|--------------------------------------------------------------|-------------------------------------|
| `payouts_by_spin_type`        | `fresh_slotlab/analyzer/features/payouts_by_spin_type.py`    | `payouts_by_spin_type`              |
| `reel_marginal_by_spin_type`  | `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` | `reel_marginal_by_spin_type`     |
| `bankruptcy_simulation`       | `fresh_slotlab/analyzer/features/bankruptcy_simulation.py`   | `bankruptcy_simulation`, `bankruptcy_probe` |
| `multiplier_profile`          | `fresh_slotlab/analyzer/features/multiplier_profile.py`      | `multiplier_profile`                |

---

## §2 Pragmatic strategy (scaffolding-first; logic-extraction opportunistic)

The full architectural ideal per §5.2 (per-round extract → reduce → emit)
requires restructuring main()'s aggregation loop, which is a multi-day
refactor. The minimum-viable for Wave 2c is **scaffolding** — get the 4
feature classes registered AND invoked, even if the heavy aggregation logic
stays in main() for now. Wave 2d/2e then build on this scaffold.

For each feature pick ONE of these patterns:

### Pattern A — Scaffolding only (recommended for `payouts_by_spin_type` and `reel_marginal_by_spin_type`)
```python
class PayoutsBySpinType(AnalyzerFeature):
    FEATURE_ID: ClassVar[str] = "payouts_by_spin_type"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only

    def extract(self, parse_state, chunk_dict) -> dict:
        return {}  # no per-round work; aggregation owned by main() for now

    def reduce(self, prev_acc, this_acc) -> dict:
        return prev_acc  # no-op accumulator

    def emit(self, final_acc, summary: dict) -> None:
        # main() already populated summary["payouts_by_spin_type"] inline.
        # This emit is a no-op verification: assert the key is present.
        # Wave 2d will move the actual aggregation here.
        assert "payouts_by_spin_type" in summary
```

### Pattern B — Logic extraction (recommended for `bankruptcy_simulation`, optional for `multiplier_profile`)
```python
class BankruptcySimulation(AnalyzerFeature):
    FEATURE_ID: ClassVar[str] = "bankruptcy_simulation"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("bankruptcy_simulation", "bankruptcy_probe")
    RTP_CONTRIBUTION: ClassVar[bool] = False

    def extract(self, parse_state, chunk_dict) -> dict:
        return {}  # bankruptcy reps already computed during chunk parsing

    def reduce(self, prev_acc, this_acc) -> dict:
        return prev_acc

    def emit(self, final_acc, summary: dict) -> None:
        # All inputs already live in summary via prior aggregation:
        #   summary["_bankruptcy_sim_totals"]  (temp key set by main())
        #   summary["_bankruptcy_mults"]
        #   summary["_bankruptcy_sim_session_spins"]
        # Convert into the final structure and del the temp keys.
        ...  # the ~45-line emit logic from main() lines 4004-4051
```

If logic extraction is too risky for any one feature, **fall back to
Pattern A**. Both patterns are acceptable; the deliverable is the 4
registered classes + main() invoking them.

---

## §3 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.2` — Plugin Protocol verbatim (ABC contract).
- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 2` — "Extract feature_* from pia.main() into analyzer/features/<feature_id>.py".
- `fresh_slotlab/analyzer/features/_base.py` — the ABC (P2-A1 deliverable).
- `fresh_slotlab/analyzer/feature_registry.py` — `register()` + `get_features_for_machine()` (P2-A1).
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — no I/O at feature module import. Registration via `register()` call is OK (pure list-append; idempotent).
- Memory `feedback_no_parallel_panel_impl.md` — do NOT create parallel renderers; feature.emit must produce the SAME summary keys as main()'s existing aggregation.

---

## §4 Contract (testable invariants)

### C1 — 4 feature modules exist
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` present
- `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` present
- `fresh_slotlab/analyzer/features/bankruptcy_simulation.py` present
- `fresh_slotlab/analyzer/features/multiplier_profile.py` present
- Each implements `AnalyzerFeature` (instantiable; ABC methods are concrete)

### C2 — Registration on import
Importing each feature module appends its class to
`feature_registry.ALL_FEATURES`. Duplicate import is a no-op (registry
already dedups by FEATURE_ID).

### C3 — P1-A1 canary stays GREEN
`tests/integration/test_analyzer_three_invocation_parity.py` 23/23. The
summary key bytes must remain identical to pre-Wave-2c — the 4 features
either pass-through (Pattern A) or produce byte-identical output
(Pattern B).

### C4 — main() invokes each feature
After main()'s existing aggregation builds the summary dict but BEFORE the
JSON write, main() does:
```python
from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
# Wave 2c: invoke each registered feature's emit. For Pattern A features
# this is a no-op verification; for Pattern B features this is the
# extracted aggregation logic.
for feature in ALL_FEATURES:
    feature.emit(None, summary)
```
(Manifest filtering via `get_features_for_machine` is deferred to Phase 3
when per-machine manifest JSON files land; until then `ALL_FEATURES`
substitutes.)

### C5 — Hash composition
After the 4 modules exist, `compute_base_analyzer_version()` is unchanged
(it only hashes core/*.py, not features/*.py per §4.1).
`compute_effective_analyzer_version(machine_id="M14", mode=1)` reads the
manifest's `analyzer_features` list (or empty if no manifest), and hashes
the matching feature classes via `feature.compute_hash()`. For machines
with no manifest yet, the version is the base hash alone — unchanged
behavior.

### C6 — Subprocess import safety
- `python -c "import fresh_slotlab.analyzer.features.payouts_by_spin_type"` rc=0 no stderr.
- Same for other 3 features.

### C7 — All existing tests pass
- 9-suite Phase 1+2 regression: 647+ GREEN.
- New `tests/backend/test_wave_2c_universal_features.py` (~30+ tests).

### C8 — Inject-bug TDD
- Inject: remove `register()` call from one feature → ALL_FEATURES doesn't include it → emit-invocation test RED.
- Inject: in a Pattern B emit, change one output field value → P1-A1 parity canary RED (byte mismatch).

---

## §5 Out of scope

- Manifest-driven per-machine feature filtering (Phase 3).
- Per-round extract logic for Pattern A features (Wave 2d if needed).
- Other waves' features (cluster-shared, bespoke, RTP gate).
- main() body refactor to thin shim (Wave 2c-2f arc).
- Frontend changes.

---

## §6 Risk + rollback

**Risk class**: MEDIUM. Main risks:
1. **Summary byte drift.** Pattern B emit MUST produce the identical
   summary keys as main()'s pre-Wave-2c aggregation. P1-A1 parity canary
   is the canonical guardrail.
2. **Registration order.** ALL_FEATURES preserves registration order;
   main() invokes in that order. If a feature's emit reads a key produced
   by another feature's emit, ordering matters. For Wave 2c all 4
   features are independent (read from already-populated state); no
   inter-feature dependencies.
3. **Pattern B for bankruptcy_simulation has the temp-key pattern**:
   main() sets `summary["_bankruptcy_sim_totals"]` and similar temp keys
   before invoking features; feature.emit reads + deletes them. If a
   future feature also reads those temp keys, ordering matters. Document
   the contract.

Rollback: single commit. `git revert <sha>` removes 4 feature modules +
the main() emit loop.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — create 4 feature modules. For bankruptcy_simulation
  and multiplier_profile, attempt Pattern B (logic extraction). For
  payouts_by_spin_type and reel_marginal_by_spin_type, use Pattern A
  (scaffolding). Wire main() to invoke ALL_FEATURES after existing
  aggregation. Verify P1-A1 canary GREEN throughout.

- `impl-tester` — write `tests/backend/test_wave_2c_universal_features.py`
  covering C1-C8. For each feature: existence test, registration test,
  emit-invocation test, schema test (assert summary keys present and
  bytes match). Inject-bug for at least 2 contracts.

### Wave 2 (parallel)
- `impl-verifier` — P1-A1 canary + 9-suite regression + 4 subprocess
  smokes + ALL_FEATURES contents check + summary byte parity.
- `impl-critic` — adversarial: did Pattern B byte-drift the summary?
  Did Pattern A actually deliver anything beyond a registration? Is the
  registration idempotent under double-import (e.g. via pytest re-run)?

Expected wall time: ~120-180 min (4 features + main() wiring).
