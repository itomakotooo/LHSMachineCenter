# 02_implementation.md — P1-B3 Session CI Half-Width Dedup

## Verdict

**pass**

---

## Files changed (3 files)

| File | Lines affected | Change |
|------|---------------|--------|
| `fresh_slotlab/sampler.py` | +42 lines after line 216 | Added canonical `session_halfwidth_pp(n, ret_sum, ret_sq_sum)` |
| `fresh_slotlab/player_impact_analyzer.py` | Import block + lines ~991-1013 | Added import (both package + standalone paths); removed local 22-line definition |
| `slot_designer/core/backend/virtual_analyzer.py` | Import line 77 + lines ~253-285 | Added import; replaced 19-line function body with module-level alias |

---

## Brief-section traceability

| Change | Brief section | Arch ref |
|--------|--------------|---------|
| `session_halfwidth_pp` added to `sampler.py` as canonical | §1 "move canonical to `fresh_slotlab/sampler.py`" | `03_coupling_audit.md §4.5` |
| `player_impact_analyzer.py` local definition removed, import added | §1 "Both callsites drop local + import canonical" / §3 C2 | `08_handoff.md §4 Phase 1` |
| `virtual_analyzer.py` local `_ci_halfwidth_pp` body removed, alias added | §1 "Both callsites drop local" / note re internal callers (lines 864, 984, 1021) | `03_coupling_audit.md §4.5` |
| Both package-import and standalone-script fallback updated in `player_impact_analyzer.py` | Established pattern from P1-B4 (P1-B3 §2 cites P1-B4 dependency) | — |

---

## Known consumers of `session_halfwidth_pp` / `_ci_halfwidth_pp` (P1-B3 round-2 R2 enumeration)

Per memory `feedback_enumerate_safety_paths.md`, every consumer enumerated:

| Consumer | File:line | Imports | Status post-dedup |
|---|---|---|---|
| Analyzer in-process replay loop | `fresh_slotlab/player_impact_analyzer.py:991-1013` | `session_halfwidth_pp` (via re-export) | Calls re-exported `session_halfwidth_pp` (same callable as canonical) |
| Virtual analyzer sim loop | `slot_designer/core/backend/virtual_analyzer.py:852/972/1009` | `_ci_halfwidth_pp = session_halfwidth_pp` (module alias) | Calls alias (same callable as canonical) |
| Test: virtual_analyzer ci_stop | `slot_designer/tests/test_virtual_analyzer_ci_stop.py:45` | `from virtual_analyzer import _ci_halfwidth_pp` | 11/11 PASS via alias |
| Test: P1-B3 canonical | `tests/backend/test_session_halfwidth_canonical.py` | `from fresh_slotlab.sampler import session_halfwidth_pp` | 24/24 PASS |
| Test: analyzer resume (round-2 R2 NEW) | `tests/backend/test_analyzer_resume.py::TestSessionHalfwidthHelper:71` | `from fresh_slotlab.player_impact_analyzer import session_halfwidth_pp` (re-export) | Imports via PIA re-export; tests pass per verifier full-suite run |

---

## Design decisions

### `_ci_halfwidth_pp = session_halfwidth_pp` alias in `virtual_analyzer.py`

The brief noted that `_ci_halfwidth_pp` is called at three internal sites (lines 852, 972, 1009 post-edit) and is also imported by `slot_designer/tests/test_virtual_analyzer_ci_stop.py` (line 45). Rather than renaming all callers (which is out of scope for a pure dedup ticket — per invariant "minimal delta"), a module-level alias preserves both:
- (a) all internal callers unchanged
- (b) test imports unchanged (§3 C6)

The alias is a simple assignment — not a `def` — so C1's grep on `"def _ci_halfwidth_pp\b"` returns zero results (only `session_halfwidth_pp` in `sampler.py` has a `def`).

### Positional-signature compatibility

The canonical `session_halfwidth_pp(n, ret_sum, ret_sq_sum)` is positionally identical to the old local `session_halfwidth_pp(ret_count, ret_sum, ret_sq_sum)` — parameter `n` vs `ret_count` is a name-only difference. All existing callsites pass positional args, so no callers need updating.

---

## Pytest results (touched modules)

```
tests/backend/test_t_critical_table_canonical.py   — all pass (P1-B4 canonical + C6 split-path)
slot_designer/tests/test_virtual_analyzer_ci_stop.py — all pass (C6 existing test)
fresh_slotlab/ (full module scan)
================================================================
1246 passed in 0.74s
```

---

## C1 verification

```
grep -rn "def session_halfwidth_pp\|def _ci_halfwidth_pp" fresh_slotlab/ slot_designer/ src/
→ fresh_slotlab/sampler.py:219:def session_halfwidth_pp(...)
```

Exactly one `def` in the codebase. The `_ci_halfwidth_pp = session_halfwidth_pp` line in `virtual_analyzer.py` is an assignment, not a definition — does not violate C1.

---

## Open issues / out-of-scope

1. **impl-tester C7 inject-bug TDD** — the brief §3 C7 asks the tester to revert the dedup, inject a divergent formula into one old location, and assert the regression test catches it. This is tester's responsibility per §7 Wave 1 parallel split. Not implemented here.

2. **`tests/backend/test_session_halfwidth_canonical.py`** (new) — brief §1 lists this as the tester's deliverable. Not created here (single-responsibility: tester writes tests, implementer writes code).

3. **`compute_ci_halfwidth_pp` in sampler.py** — brief §4 explicitly out-of-scope (chunk-level CI, different formula). Not touched.

---

## Risk notes for impl-critic

- The `_ci_halfwidth_pp = session_halfwidth_pp` alias means that monkeypatching `va._ci_halfwidth_pp` in tests would shadow only the alias, not `session_halfwidth_pp` itself. The existing test `test_c6_split_path_monkeypatch_proves_sampler_attr_used` patches `sampler.t_critical_95` and `va.t_critical_95` (the imported binding), which correctly exercises the split path. This test continues passing post-change.

- `math` is already imported in `sampler.py` (line 6). No new imports needed beyond adding the function body.

- No import-time side effects introduced in `sampler.py` — the new function is a pure def, no module-level execution (per memory `feedback_subprocess_import_suicide_and_module_globals.md`).
