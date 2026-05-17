# Ticket P1-B1 — Consolidate `_lookup_machine_md5` (real × 2) (Batch 1c)

> Phase 1 / Batch 1c. First of the 5 real ↔ virtual dedups (excluding P1-B4 which was the proof-of-concept). Depends on Batch 1a (P1-A2 parity test must exist).

---

## §1 Ticket scope

`_lookup_machine_md5` is defined twice with the same body (reads `configs/machines.json` and returns the machine's stamped md5):
- [src/web_console/backend/app.py:548-591](src/web_console/backend/app.py:548)
- [fresh_slotlab/player_impact_analyzer.py:2163-2184](fresh_slotlab/player_impact_analyzer.py:2163)

Consolidate to one canonical location; both callsites import.

Files expected to change:
- `fresh_slotlab/machine_md5.py` (new) — canonical `lookup_machine_md5(machine, machines_config_path) -> (code_md5, config_md5)`
- `src/web_console/backend/app.py:548-591` — drop local, import canonical
- `fresh_slotlab/player_impact_analyzer.py:2163-2184` — drop local, import canonical
- `tests/backend/test_lookup_machine_md5_canonical.py` (new) — regression per §3

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §4` row 1 ("md5 computation for chunk stamping")
- `session_artifacts/_arch/03_coupling_audit.md §4.5` — duplicate primitives
- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.1` — Phase 1 dedup
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — md5 lookup × 2
- Memory `feedback_no_parallel_panel_impl.md` — reuse over re-impl
- Memory `feedback_md5_granularity_and_stamping.md` — md5 path stamping discipline

---

## §3 Contract (testable invariants)

### C1 — Single source of truth
`grep -rn "def _lookup_machine_md5\b\|def lookup_machine_md5\b" fresh_slotlab/ src/` returns exactly one definition (in `fresh_slotlab/machine_md5.py`).

### C2 — Both callsites delegate
`app.py:548-591` body is `from fresh_slotlab.machine_md5 import lookup_machine_md5` (or thin wrapper if signature must change). `player_impact_analyzer.py:2163-2184` similarly.

### C3 — Value parity preserved
For each of `[M14, M37, M101, M260, M279]` (mix of SC-Vanilla + complex archetypes): `lookup_machine_md5(M)` returns the same `(code_md5, config_md5)` as the pre-dedup implementations. Verifiable by snapshot test against current production `configs/machines.json` values.

### C4 — Virtual cousin documented
`compute_machine_md5_for_mode` in `slot_designer/core/backend/machine_version.py:276-309` is the virtual-side equivalent (different schema — virtual computes from spec+weights+plugins, not from configs/machines.json). The relationship is documented in the canonical helper's docstring; the two are NOT merged in this ticket (different purposes).

### C5 — P1-A2 parity test stays green
After the dedup, the P1-A2 three-writer parity test (Batch 1a) must continue passing — md5 values must agree across all 3 writers, since one of them (α) now imports from the canonical location.

### C6 — Inject-bug TDD
Tester: revert the dedup, inject a divergent value into one of the two old locations → assert the regression test catches the divergence by checking the other location returns the original. Document in `03_tests.md`.

---

## §4 Out of scope

- Merging real and virtual md5 computations (different schemas)
- Changing the md5 algorithm
- Touching `compute_code_md5` / `compute_config_md5` (different functions, different scope)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores both local implementations.

---

## §6 Risk + rollback notes

**Risk class**: LOW-MEDIUM.

**Dependency**: P1-A2 (Batch 1a) parity test must be landed before this ticket — needed as regression net.

**Subprocess mode**: `player_impact_analyzer.py` is spawned as a subprocess. Per memory `feedback_subprocess_import_suicide_and_module_globals.md`: ensure the new `fresh_slotlab/machine_md5.py` has no import-time side effects (no `app = build_app()` etc.). impl-verifier spawns analyzer subprocess to confirm clean import.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — extracts canonical, updates 2 callsites, runs touched-module pytest
- `impl-tester` — writes regression + inject-bug log

### Wave 2 (parallel)
- `impl-verifier` — runs P1-A2 parity test (must stay green), runs full pytest, spawns analyzer subprocess to verify import works
- `impl-critic` — checks: was the virtual cousin relationship documented? Any callsite missed in grep (e.g., other modules also lookup md5)?

Expected wall time: ~30-45 min.
