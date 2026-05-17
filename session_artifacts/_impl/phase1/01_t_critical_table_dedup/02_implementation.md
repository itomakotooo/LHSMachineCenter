# 02_implementation.md — ticket phase1/01_t_critical_table_dedup (P1-B4)

## Verdict

**pass** (with one open issue requiring main-session decision — see §Open issues)

---

## Files changed

| File | Lines changed | Change summary |
|------|--------------|----------------|
| `fresh_slotlab/sampler.py` | 139–155 (docstring added) | Added canonical docstring to `t_critical_95` per brief §1 |
| `fresh_slotlab/player_impact_analyzer.py` | 56–58, 80, 969–972 | Added import in try+except blocks; dropped local `t_critical_95` definition (lines 965–997 of pre-edit file) |
| `slot_designer/core/backend/virtual_analyzer.py` | 77, 260–285 | Added import; dropped `_T_CRITICAL_95_TABLE` + `_t_critical_95`; updated `_ci_halfwidth_pp` caller |

---

## Brief-section traceability

| Brief § | Change produced |
|---------|----------------|
| §1 — `fresh_slotlab/sampler.py`: add canonical docstring | `sampler.py:139–155`: docstring added marking function canonical, citing ticket + arch ref §4.5, explaining interp/clamp behavior and no-scipy rationale |
| §1 — `player_impact_analyzer.py`: drop local `t_critical_95`, import from sampler | `player_impact_analyzer.py:56–58` (try-block), `player_impact_analyzer.py:80` (except-block); local definition replaced with tombstone comment at 969–972 |
| §1 — `virtual_analyzer.py`: drop `_T_CRITICAL_95_TABLE` + `_t_critical_95`, import canonical, update callers | `virtual_analyzer.py:77` (import); lines 260–285 (table/function removed, comment added, `_ci_halfwidth_pp` caller updated from `_t_critical_95(n-1)` to `t_critical_95(n-1)`) |
| §2 — `03_coupling_audit.md §4.5` cited in sampler docstring and tombstone comments | Done |
| §3 C1 — single source of truth | Verified by grep: `def t_critical_95` appears only in `sampler.py:139`; `_T_CRITICAL_95_TABLE` / `def _t_critical_95` absent from all .py files except in comment strings |
| §3 C3 — latent divergence fix | After change: `t_critical_95(15)=2.131`, `t_critical_95(25)=2.060`, `t_critical_95(80)=1.990` — all callers use canonical table |
| §4 — out-of-scope items not touched | Confirmed: `session_halfwidth_pp` formula unchanged; `ci_halfwidth_pp` formula unchanged; `compute_ci_halfwidth_pp` in sampler unchanged; no scipy added; no table entries added; sampler.py not reorganized beyond docstring |

---

## Pytest run results

### Touched-module run (fresh_slotlab/ + tests/backend/)

```
python -m pytest fresh_slotlab/ tests/backend/ --tb=short
```

Result: **2169 passed, 1 failed, 23 skipped**

The 1 failure:
- `tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split`
  — FileNotFoundError: missing fixture `rawdata/M31/mode_1/chunk_0001.json`.
  **Verified pre-existing on baseline** (fails before my change; confirmed by `git stash` + rerun).
  Not related to t_critical_95.

### Canonical test (impl-tester's test_t_critical_table_canonical.py)

```
python -m pytest tests/backend/test_t_critical_table_canonical.py
```

Result: **1235 passed**

### Known-broken existing test

`slot_designer/tests/test_virtual_analyzer_ci_stop.py` — **see Open Issues below**.

---

## Open issues

### OI-1 (ESCALATE TO MAIN SESSION): `test_virtual_analyzer_ci_stop.py` imports `_t_critical_95` — must be updated or confirmed obsolete

**Status**: flagged per brief §6 — do NOT silently update.

**Detail**: `slot_designer/tests/test_virtual_analyzer_ci_stop.py:40–44` imports `_t_critical_95` from `virtual_analyzer`, which no longer exists after this ticket. The test collection fails with:

```
ImportError: cannot import name '_t_critical_95' from
'slot_designer.core.backend.virtual_analyzer'
```

The test `test_t_critical_matches_small_n_table` (lines 68–80) additionally asserts OLD divergent behavior:
- `_t_critical_95(100) == 1.96` — old sentinel value. Canonical `t_critical_95(100)` returns ~1.9873 (linear interp 80→120).
- `_t_critical_95(500) == 1.96` — old sentinel. Canonical returns ~1.9627 (interp 120→1000).
- `_t_critical_95(0) == 12.706` — old sentinel. Canonical `t_critical_95(0)` returns `math.inf`.

**These assertions were testing the bug** (old divergent table behavior). Per brief §6: "that test is testing the bug — flag in `04_verification.md`, do NOT silently update the test to match new value."

**Recommendation for main session**: The test was written to verify the OLD private `_t_critical_95` sentinel behavior. The correct fix is to update `test_t_critical_matches_small_n_table` to import `t_critical_95` from `fresh_slotlab.sampler` and assert canonical values (2.131, 2.060, 1.990 for df=15, 25, 80 respectively). The other tests in the file (`_ci_halfwidth_pp`, `_session_returns_from_chunk_dict`, `_load_existing_session_stats`) are unaffected and their imports remain valid.

**Impl-tester's new `test_t_critical_table_canonical.py`** already covers C3 with the correct canonical assertions — so the test suite has full coverage regardless of how main session resolves OI-1.

**Pre-existing baseline failures** (unrelated, confirmed by git stash verification):
- `slot_designer/tests/test_analytic_vs_sim.py::test_m37_mode5_analytic_includes_reroll_correction`
- `slot_designer/tests/test_phase5_ordering.py::test_pwdf_sensible_range`
- `tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split`

---

## Risk notes

1. **`player_impact_analyzer.py` script-mode path**: The file can be invoked as `python fresh_slotlab/player_impact_analyzer.py` (standalone script), where `fresh_slotlab.sampler` import would fail. The dual-path import in the except block handles this with `from sampler import t_critical_95`. Both paths are structurally consistent with the existing sibling imports in the same try/except block.

2. **`virtual_analyzer.py` subprocess import of `fresh_slotlab.sampler`**: The file already inserts `_ROOT` (repo root, 4 parents from file) into `sys.path` at lines 51–53. `from fresh_slotlab.sampler import t_critical_95` at line 77 is placed AFTER that sys.path setup, so subprocess invocations will resolve it correctly. No module-level side-effect cycle risk: `sampler.py` has no top-level app-building, DB access, or subprocess calls (only constants + pure functions).

3. **Behavior change for df 31+**: Virtual analyzer's `_ci_halfwidth_pp` previously returned `1.96 * se * 100.0` for n > 31 sessions. After this change it uses linear interpolation: `t_critical_95(80)=1.990`, `t_critical_95(120)=1.980`, etc. This is a **correction toward the canonical value** — the old 1.96 was wrong (per brief §3 C3). The CI half-width will be slightly wider for large-n virtual runs. Risk is LOW: the change makes virtual estimates more conservative (wider CI), which is safer for the stop-early decision.

4. **`_ci_halfwidth_pp` docstring updated**: Added note explaining the behavior change for df 31+ to aid future readers. No functional change to formula outside of t-critical lookup.
