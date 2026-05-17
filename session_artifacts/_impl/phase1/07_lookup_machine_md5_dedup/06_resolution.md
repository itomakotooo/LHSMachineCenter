# Ticket P1-B1 — Resolution

> Main session consolidation: W1 + W2 + main-session R2+R3 fixes.

## Decision: **SHIP**

| Source | Verdict |
|---|---|
| impl-implementer | PASS (~13 min) — 3 files; 69/69 pytest (30 P1-A2 parity + 39 new) |
| impl-tester | sufficient (~11 min) — 39 tests; 6/6 inject-bug verified |
| impl-verifier | PASS (~7.6 min) — C1+C5 verified independently; 39/39 new tests pass; 2252/2254 backend (4 pre-existing); 0 regressions |
| impl-critic | APPROVE-WITH-REVISIONS — R1 verifier pending (resolved by completion); R2 except too broad; R3 batch_dev_sampler 3rd callsite missed |

## Round 2 fixes (main session)

**R2 — Narrow exception in `_get_machine_md5` at `app.py:597`**:
Changed `except Exception` to `except (OSError, json.JSONDecodeError, TypeError)` matching canonical `fresh_slotlab.machine_md5.lookup_machine_md5` exception spec. Added comment explaining the narrowing rationale per memory `feedback_dont_swallow_errors_in_fix.md`.

**R3 — Migrate `batch_dev_sampler.py` (third callsite)**:
Critic found 3rd callsite at `fresh_slotlab/batch_dev_sampler.py:43,54,176`. Implementer's `as _lookup_machine_md5` alias on PIA preserved backward compat (sampler kept working), but the indirect chain (sampler → PIA → canonical via alias) violates the "every safety path enumerated and migrated" discipline (memory `feedback_enumerate_safety_paths.md`). Main session migrated sampler to import from canonical directly with own `as _lookup_machine_md5` alias preserving the local name.

Verified: `python -c "from fresh_slotlab.batch_dev_sampler import _lookup_machine_md5; r = _lookup_machine_md5('M14'); ..."` returns `('4fcf00c48b...', '536fc5a2a8...')` correctly.

## Pytest after R2+R3

- 69/69 targeted pass (30 P1-A2 parity + 39 new canonical tests)
- C1 single-definition test still GREEN (aliases don't count as `def`)
- `_get_machine_md5` narrow-exception change tested implicitly (P1-A2's TestEdgeCases::test_beta_returns_empty_for_unknown_machine still PASS — return on KeyError-like miss still works because the inner `m.get("machine")` check handles it without exception)

## Architectural note (for P1-B2 and beyond)

The `as _lookup_machine_md5` alias pattern is now established convention:
- Canonical lives at `fresh_slotlab/machine_md5.py:lookup_machine_md5`
- Modules that need the legacy underscore-prefixed name (for monkeypatch compatibility) import with `as _lookup_machine_md5`
- C5 split-path test (`tests/backend/test_summary_md5_writer_parity.py:test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`) confirms the alias correctly forwards monkeypatches to the canonical via PIA's call site

P1-B2 (summary md5 patcher consolidation) will use the same canonical lookup via this established import pattern.

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `fresh_slotlab/machine_md5.py` NEW
- `fresh_slotlab/player_impact_analyzer.py` MODIFIED (drop local def + import alias)
- `src/web_console/backend/app.py` MODIFIED (delegate `_get_machine_md5` flat-schema path + narrow exception per R2)
- `fresh_slotlab/batch_dev_sampler.py` MODIFIED (R3: import canonical directly)
- `tests/backend/test_lookup_machine_md5_canonical.py` NEW (39 tests)
- 6 markdown artifacts in `session_artifacts/_impl/phase1/07_lookup_machine_md5_dedup/`
