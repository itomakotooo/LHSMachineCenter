# 02_implementation.md — Ticket P1-B1: Consolidate `_lookup_machine_md5` (real × 2)

**Verdict**: PASS

---

## Files changed (3)

| File | Change | Lines |
|------|--------|-------|
| `fresh_slotlab/machine_md5.py` | NEW — canonical `lookup_machine_md5` | 1–97 |
| `fresh_slotlab/player_impact_analyzer.py` | Replace local `def _lookup_machine_md5` with import alias | ~58–83, 2138–2144 |
| `src/web_console/backend/app.py` | Rewrite `_get_machine_md5` to delegate flat-schema path to canonical | 548–597 |

---

## Brief-section traceability

| Change | Brief §§ | Arch artifact |
|--------|----------|---------------|
| Create `fresh_slotlab/machine_md5.py` with canonical `lookup_machine_md5(machine, machines_config_path)` | §1 deliverables, §3 C1 | `04_v5 §6.1` Phase 1 dedup |
| `player_impact_analyzer.py`: remove `def _lookup_machine_md5`, add import alias via dual-path try/except block | §1, §3 C2, §3 C5 | `08_handoff §4 Phase 1` |
| `app.py`: rewrite `_get_machine_md5` — modesMd5 overlay stays, flat-schema fallback delegates to `lookup_machine_md5` | §1, §3 C2, §6 risk notes | `04_v5 §6.1` |
| `machine_md5.py` docstring documents virtual cousin (`compute_machine_md5_for_mode`) | §3 C4, §4 out-of-scope | `03_coupling_audit §4.5` |
| No import-time side effects in `machine_md5.py` | §6 subprocess mode note | memory `feedback_subprocess_import_suicide_and_module_globals.md` |
| Canonical return order: `(config_md5, code_md5)` matching `pia.py:2138` | §3 C3 (main-session RR3 fix) | N/A — preserved from pre-dedup |

---

## Implementation decisions

### 1. Dual-path import in `player_impact_analyzer.py` (matches existing pattern)

`player_impact_analyzer.py` is invoked both as a package member (`from fresh_slotlab.player_impact_analyzer import ...`) and as a standalone script (`python fresh_slotlab/player_impact_analyzer.py`). Existing sibling imports use a `try: from fresh_slotlab.X import Y / except ImportError: from X import Y` pattern. The `machine_md5` import was added to both branches of this existing try/except block (lines ~58 and ~83).

The old `def _lookup_machine_md5` (22 lines at old ~2138) was removed and replaced with a 5-line comment block citing the ticket, making the delegation explicit.

### 2. `_lookup_machine_md5` remains a module-level attribute in pia (monkeypatching preserved)

The import `from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lookup_machine_md5` binds `_lookup_machine_md5` as a name in `player_impact_analyzer`'s module namespace. `monkeypatch.setattr(pia, "_lookup_machine_md5", sentinel)` replaces this namespace binding, and the call `_lookup_machine_md5(machine)` inside `_save_chunk_cache` resolves through the module global dict — picks up the monkeypatched value. This is the exact pattern tested by `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` in P1-A2 parity tests (30/30 still passing).

### 3. `app.py: _get_machine_md5` — thin wrapper, modesMd5 overlay stays

`_get_machine_md5` in `app.py` is a superset of `_lookup_machine_md5` in `pia.py`: it adds per-mode `modesMd5` dispatch (virtual machine schema introduced 2026-04-22). The brief says "thin wrapper if signature must change". Implementation:
- `mode is not None`: try to find `modesMd5[str(mode)]` entry in the JSON. If found and valid → return it. If machine not found or no modesMd5 for this mode → `break` / fall through.
- All paths ultimately call `lookup_machine_md5(machine, target)` for the flat-schema case.
- The `_get_machine_md5` local def is retained (not removed) because it has a different signature and is called at 8+ callsites in `app.py` with `mode=` args. Removing it would be out of scope.

The lazy import pattern (`from fresh_slotlab.machine_md5 import lookup_machine_md5` inside the function body) matches existing `app.py` style for `fresh_slotlab` imports.

### 4. `batch_dev_sampler.py` — no change needed

`batch_dev_sampler.py` imports `_lookup_machine_md5` from `player_impact_analyzer` at its module top (lines 43, 54). After this change, `pia._lookup_machine_md5` is the canonical function (imported from `machine_md5.py` under that name). `batch_dev_sampler.py` continues to work without modification — it gets the canonical implementation transitively.

---

## Pytest results

### Touched-module + P1-A2 parity tests

```
tests/backend/test_summary_md5_writer_parity.py  30/30 passed
tests/backend/test_lookup_machine_md5_canonical.py  39/39 passed
Total: 69/69 passed in 0.49s
```

### Full backend test suite (excluding pre-existing failures)

```
2244 passed, 22 skipped, 2 xfailed
1 failed: test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess
  (pre-existing: StubProcess thread timeout from unrelated test ordering;
   confirmed identical failure on collab/dev baseline in full-suite run)
1 failed (baseline): test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
  (pre-existing: missing rawdata/M31/mode_1/chunk_0001.json fixture)
```

Both failures are pre-existing on `collab/dev` baseline (confirmed by `git stash` + re-run).

---

## Contract verification (§3)

| Contract | Status | Evidence |
|----------|--------|----------|
| C1 — single definition | PASS | `grep def lookup_machine_md5 fresh_slotlab/ src/` = 1 hit in `machine_md5.py` only |
| C2 — both callsites delegate | PASS | AST: no `def _lookup_machine_md5` in `pia.py`; `app.py` has only the thin-wrapper `_get_machine_md5` that calls canonical |
| C3 — value parity (config_md5 first) | PASS | 5 machines × 3 tests = 15 parametrized tests GREEN |
| C4 — virtual cousin documented, not merged | PASS | `machine_md5.py` module docstring names `compute_machine_md5_for_mode`, `machine_version`, `virtual`; cousin untouched |
| C5 — P1-A2 parity stays green | PASS | 30/30 |
| C6 — inject-bug TDD | PASS (impl-tester) | 7 inject-bug tests in `test_lookup_machine_md5_canonical.py` all GREEN |

---

## Open issues / out-of-scope deferred

1. **`batch_dev_sampler.py` import chain**: `sampler.py` still imports `_lookup_machine_md5` transitively from `pia.py`. This is correct behavior (it gets the canonical via `pia`'s alias), but a future ticket could update `batch_dev_sampler.py` to import directly from `machine_md5` for clarity. Out of scope per §4 ("Touching `compute_code_md5` / `compute_config_md5` (different functions, different scope)").

2. **`app.py: _get_machine_md5` still has a local `def`**: Brief §3 C2 acknowledges "thin wrapper if signature must change." The wrapper is retained to avoid touching 8+ callsites out of scope. impl-critic may flag that `_get_machine_md5` is not fully delegated; the flat-schema branch IS delegated; only the modesMd5 overlay logic remains local.

---

## Risk notes

- **Subprocess import**: verified clean via `subprocess.run([sys.executable, '-c', 'import fresh_slotlab.machine_md5'])` → rc=0, empty stdout/stderr. Test `TestImportSmoke::test_import_machine_md5_is_side_effect_free` GREEN.
- **Monkeypatch chain**: `pia._lookup_machine_md5` remains a module-level name. Monkeypatching `pia._lookup_machine_md5` still propagates to `_save_chunk_cache` call site (proven by C5 split-path test GREEN).
- **`app.py` modesMd5 logic**: the rewrite introduced a `break` statement when machine is found but has no valid modesMd5 for the requested mode. The `break` ensures the loop exits cleanly and falls through to `lookup_machine_md5`. Edge cases (machine not in list, JSON error) tested by P1-A2 parity `TestEdgeCases` class (5 tests GREEN).
