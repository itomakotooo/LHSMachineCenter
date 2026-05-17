# Ticket P1-C1 — Remaining module globals + pure-function extraction (Batch 1d)

> Phase 1 / Batch 1d. Final Phase 1 ticket. Broader than the others — may be sub-divided at implementation time if scope exceeds one impl-* cycle.

---

## §1 Ticket scope

Beyond `RAWDATA_ROOT` (P1-B6), several other module globals in `src/web_console/backend/app.py` are footguns per memory `feedback_subprocess_import_suicide_and_module_globals.md`. Migrate each to instance-level or per-request memo. Additionally, extract truly-pure functions (no side effects, no state) from `app.py` / `player_impact_analyzer.py` to standalone modules to enable testing and reuse.

Per-target list from `03_coupling_audit.md §4.1`:
- `_MACHINES_SUMMARY_CACHE` ([app.py:1987](src/web_console/backend/app.py:1987))
- `_RAWDATA_OVERVIEW_CACHE` ([app.py:2030](src/web_console/backend/app.py:2030))
- `_STATIC_ATTRS_CACHE` ([app.py:2143](src/web_console/backend/app.py:2143))
- `_IN_USE_MODES` + `_IN_USE_LOCK` ([app.py:2152-2153](src/web_console/backend/app.py:2152))
- `_LOCK_CACHE` ([app.py:2178](src/web_console/backend/app.py:2178))
- `_STATIC_ATTRS_MECH_KEYS` ([app.py:2246](src/web_console/backend/app.py:2246))

Files expected to change:
- `src/web_console/backend/app.py` (multiple locations)
- Possibly new module(s) for extracted pure functions (TBD by implementer)
- `tests/backend/test_app_state_isolation.py` (new) — per-global split-path regression

---

## §2 Brief sections cited

- `session_artifacts/_arch/03_coupling_audit.md §4.1` — module-level globals inventory
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — "Pure-function extraction + module-global → instance attribute migration"
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — anti-pattern definition + instance-attr migration discipline
- Memory `feedback_enumerate_safety_paths.md` — every consumer of each global must be migrated together

---

## §3 Contract (testable invariants)

### C1 — Per-global migration plan
`02_implementation.md` lists each global with:
- Migration target (instance attr on `create_app` returned obj / per-request memo via FastAPI Depends / module deletion if truly unused)
- Consumer count + every consumer migrated
- Rollback risk per global

### C2 — Per-global split-path regression
For each migrated global, a regression test per memory `feedback_subprocess_import_suicide_and_module_globals.md`:
- Monkeypatch the (now-removed or sentinel) module global to a wrong value
- Assert behavior depends on the instance/request scope, not the global
- Inject-bug verified per global

### C3 — No new import-time side effects
Per memory: NO new module-top `app = build_app()`-like patterns introduced. impl-verifier greps for `^[A-Z_]+\s*=\s*build_\|^app\s*=\|^server\s*=` etc. at module top in any new module. None added.

### C4 — Pure function extraction (optional sub-scope)
If implementer identifies truly-pure functions worth extracting:
- New module(s) for the extracted functions
- Original location calls extracted module
- Test per extracted function asserts purity (no side effects via monkeypatched filesystem)

If implementer decides extraction is out-of-scope-for-this-ticket → document in `02_implementation.md` + flag for follow-up P1-C2.

### C5 — Multi-worker safety
Per `03_coupling_audit.md §4.1` last paragraph: existing caches `_MACHINES_SUMMARY_CACHE` etc. are per-worker state with no LRU; "multi-worker deployments rely on each worker rebuilding its own copy" today. Migration to instance attr preserves this (per-instance ≈ per-worker). Test asserts no cross-worker state leak.

### C6 — Subprocess-mode coverage
Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: spawn real subprocess (analyzer / virtual_analyzer) + verify no global is accidentally re-imported. Capture import-time output; assert no `build_*()`-like side effects.

---

## §4 Out of scope

- `RAWDATA_ROOT` (covered by P1-B6)
- `MACHINES_CONFIG`, `SERVERS_CONFIG`, `MACHINECONFIG_DIR`, `ANALYZER`, `FRONTEND_DIR`, etc. (genuine constants; not state-cache footguns; leave alone)
- `PROVIDER_MODELS` (already annotated as readonly; leave alone)
- `_BCM_CONFIG_PATH` / `CHUNK_CACHE_VERSION` / `_REMARKS_*RE` in player_impact_analyzer (constants, not state)
- `fresh_slotlab/chunk_index.py:91-92` `_SIDECAR_LOCKS` + `_LOCKS_GUARD` (intentional process-local per docstring; leave alone)

---

## §5 Rollback path

Single commit if scope stays manageable. `git revert <sha>` restores module globals.

**Sub-division option**: if scope exceeds one impl-* cycle, split into:
- P1-C1a — `_MACHINES_SUMMARY_CACHE` + `_RAWDATA_OVERVIEW_CACHE` (similar pattern)
- P1-C1b — `_STATIC_ATTRS_CACHE` + `_STATIC_ATTRS_MECH_KEYS` (similar pattern)
- P1-C1c — `_IN_USE_MODES` + `_IN_USE_LOCK` + `_LOCK_CACHE` (lock-related; coupled)
- P1-C1d — pure-function extraction (optional)
Each sub-ticket follows the same §3 contract on its subset of globals.

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM-HIGH. Broad surface; cache state in particular can mask bugs (cache hit returns wrong data after wrong-instance leak).

**Dependency**: recommended AFTER P1-B6 (RAWDATA_ROOT) so both migration patterns settle independently.

**Critic must verify**: every global in §1 list is either migrated OR justified as constant-not-state. Per memory `feedback_adversarial_self_review.md`: "we'll do this one later" without a follow-up ticket is moving goalposts.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — per-global migration + writes `02_implementation.md` with the per-global table per §3 C1
- `impl-tester` — writes per-global split-path regression per §3 C2; inject-bug per global

### Wave 2 (parallel)
- `impl-verifier` — runs full pytest; spawns analyzer + virtual_analyzer subprocesses + verifies no new import-time side effects; verifies multi-worker safety
- `impl-critic` — checks: every global migrated or justified-out? Test count matches global count? Any global silently dropped?

**Sub-division gate**: if implementer estimates >2x median ticket cycle, escalate to main session for P1-C1 sub-division per §5 sub-division option. Don't try to ship a too-large ticket; rollback risk too high.

Expected wall time: ~60-90 min if scope stays whole; ~30-45 min per sub-ticket if split.
