# Ticket P2-B1 — Carve `analyzer/core/parser.py`

> Phase 2 / Wave 2b. First of 4 core carves. **HIGH risk** per handoff (carving 8126-line PIA file).

---

## §1 Ticket scope

Extract chunk-parsing primitives from `fresh_slotlab/player_impact_analyzer.py` (PIA) into `fresh_slotlab/analyzer/core/parser.py`. PIA continues to expose the original symbols via `from ... import` so all existing callers (`main()`, tests, etc.) keep working unchanged.

Files expected to change:
- `fresh_slotlab/analyzer/core/__init__.py` (new package marker)
- `fresh_slotlab/analyzer/core/parser.py` (new — receives the moved code)
- `fresh_slotlab/player_impact_analyzer.py` (delete the moved bodies; replace with re-export imports — backward compat)
- `tests/backend/test_analyzer_core_parser.py` (new — regression tests for the carved surface)

**Functions to move** (per PHASE_2_TICKETS.md Wave 2b row P2-B1):
- `parse_chunk_response` (PIA line 2304 — the BIG one, ~1857 lines)
- `parse_rounds` (line 1004)
- `_check_round_schema` (line 1442)
- `parse_paylines` (line 1464)
- `split_symbols` (line 1470)
- `parse_freespin_remarks` (line 1728)
- `_compute_bonus_correction` (line 1778)
- `_compute_nf_correction` (line 1831)
- `parse_rln_codes` (line 1844)
- `_compute_upstream_schema_fingerprint` (line 2075)
- `load_chunk_envelope` (line 2004)
- `peek_chunk_envelope` (line 2050)
- `_payload_sha256` (line 1999)
- `_canonical_payload_bytes` (line 1987)
- `ChunkIntegrityError` class (line 1976)
- `_REMARKS_FREESPIN_RE`, `_REMARKS_EXTRARATIO_RE`, `_REMARKS_ADDFREESPINS_COUNT_RE` (line 1756-58 module-level regex constants used by parsing helpers)
- `_BASELINE_ROUND_FIELDS`, `_REQUIRED_ROUND_FIELDS`, `_REQUIRED_BET_FIELDS_ANY` (line 1444-1473 used by `_check_round_schema`)
- `_ENVELOPE_PEEK_BYTES`, `_ENVELOPE_PEEK_RE` (line 2074-75 used by `peek_chunk_envelope`)

**Out of scope** (stays in PIA):
- `pia.main()` itself (per §5.8 stays as thin orchestrator; calls into core/* via imports)
- HTTP layer (`post_json`, `post_json_with_retry`, `aimd_tune`, `make_payload`) — P2-B4 (`base_pipeline.py`)
- Aggregation logic — P2-B2 (`aggregator.py`)
- Writer logic (`_save_chunk_cache`) — P2-B3 (`writer.py`)
- Versioning helpers (already done by P2-A1)

---

## §2 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 1` — "Carve core/ (4 files)"
- `session_artifacts/_arch/04_architecture_proposal_v5.md §4.1` — `compute_base_analyzer_version()` hashes `core/*.py` so the carved files become the hash source for the base hash
- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.8` — `pia.main` stays as thin orchestrator; monkey-patches attach at same attribute; **Phase 1 P1-A1 3-invocation parity test must still pass**
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — no new module-top side effects
- Memory `feedback_respect_existing_codebase.md` — minimal-delta carve; don't refactor function bodies beyond what's needed to relocate them
- Memory `feedback_no_parallel_panel_impl.md` — re-exports in PIA preserve backward compat; don't create parallel versions

---

## §3 Contract (testable invariants)

### C1 — Files exist + parser symbols moved
After ticket:
- `fresh_slotlab/analyzer/core/__init__.py` present (package marker)
- `fresh_slotlab/analyzer/core/parser.py` present with all 15 functions/classes + 8 module-level constants from §1 above
- PIA still imports/re-exports these symbols so `from fresh_slotlab.player_impact_analyzer import parse_chunk_response` etc. still works (backward compat with `_batch_gen_worker.py`, `batch_dev_sampler.py`, in-process `_run_generate_report`, tests)

### C2 — `pia.main()` unchanged behavior (P1-A1 3-invocation parity stays GREEN)
The Phase 1 P1-A1 parity test (`tests/integration/test_analyzer_three_invocation_parity.py`) MUST stay green post-carve. All 3 invocation paths produce byte-identical summary against M14 mode 1 cached fixture.

### C3 — Re-export pattern preserved
PIA's module surface (what gets imported by external callers) is unchanged. Anyone doing `import fresh_slotlab.player_impact_analyzer as pia; pia.parse_chunk_response(...)` still works. Per P1-B1 + P1-B3 established `as alias` pattern, the re-exports use either `from ... import X` (which auto-creates `pia.X` attribute) or explicit `X = core.parser.X` assignment.

### C4 — Subprocess import safety
Per memory `feedback_subprocess_import_suicide_and_module_globals.md`:
- `fresh_slotlab/analyzer/core/__init__.py` has zero side effects
- `fresh_slotlab/analyzer/core/parser.py` has zero side effects (constants + function defs only; no I/O at import)
- Subprocess smoke: `python -c "import fresh_slotlab.analyzer.core.parser; print('OK')"` rc=0, no stderr

### C5 — Hash composition impact verified
After P2-A1, `compute_base_analyzer_version()` is supposed to hash `core/*.py`. With P2-B1 actually creating `core/parser.py`, this hash is no longer empty. Test asserts:
- `compute_base_analyzer_version()` returns 12-char hex
- Editing `core/parser.py` flips the hash (deterministic regression on file edit)

### C6 — All existing tests pass
- `tests/integration/test_analyzer_three_invocation_parity.py` (P1-A1) — 23/23 stay GREEN
- `tests/backend/test_lookup_machine_md5_canonical.py` (P1-B1) — 39/39 stay GREEN
- `tests/backend/test_summary_md5_writer_parity.py` (P1-A2) — 30/30 stay GREEN
- `tests/backend/test_analyzer_foundation.py` (P2-A1) — 57/57 stay GREEN
- `tests/backend/test_manifest_loader.py` (P2-A2) — 99/99 stay GREEN
- ANY existing test that imports parser symbols from `pia` continues to work via re-export

### C7 — No `try: ... except: pass` swallow added
Per memory `feedback_dont_swallow_errors_in_fix.md`. The carve preserves PIA's existing error handling; doesn't add new silent catches.

### C8 — Inject-bug TDD
- Inject: delete one re-export line in PIA → existing test that uses `pia.parse_chunk_response` goes RED
- Inject: change `core/parser.py:parse_chunk_response` body → core/* hash changes
- Inject: add an `import logging; logging.basicConfig()` at top of `core/parser.py` (side effect) → subprocess smoke catches it

---

## §4 Out of scope

- Refactoring `parse_chunk_response` internal logic (literal cut/paste only)
- Splitting `parse_chunk_response` into smaller functions (separate refactor; out of Wave 2b scope)
- Removing `compute_analyzer_version` legacy (defer to P2-B4 if appropriate)
- Adding new parser features
- Frontend changes
- Slot-* team's `slot_designer/core/engine/*.py` carve (out of project scope per addendum)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores all PIA functions to original locations + deletes `core/parser.py`. Re-export lines disappear; existing callers fall back to PIA's own implementations (which are restored).

---

## §6 Risk + rollback notes

**Risk class**: HIGH. `parse_chunk_response` is ~1857 lines; this is the BIG one. Internal function calls may reference other PIA symbols not in the carve (which would need to remain importable). Implementer must:
1. Move the function bodies
2. Add `from fresh_slotlab.analyzer.core.parser import (...)` at top of PIA for backward compat
3. Verify all PIA → core/parser direction imports + core/parser → PIA direction don't create cycles

**Cycle risk**: if `parse_chunk_response` calls a function that stays in PIA, and PIA imports from `core.parser`, that's a circular dependency. Solutions: (a) move the called function too, (b) pass the function as argument, (c) lazy import inside the function. Implementer's judgment.

**P1-A1 parity test is the canary**: if this test stays GREEN after the carve, the 3 invocation paths still produce identical summaries. If it goes RED, something architectural broke (likely cycle or missing re-export).

**Per P1-B6 hallucination + P2-A1 spec deviation**: implementer must verify on disk (file exists at new path; PIA functions deleted from old location; re-exports work) and run pytest yourself before claiming pass.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — moves the 15 functions + 8 constants per §1; adds re-exports in PIA; verifies P1-A1 parity test still green
- `impl-tester` — writes `tests/backend/test_analyzer_core_parser.py` per §3 contracts C1-C8 + inject-bug

### Wave 2 (parallel)
- `impl-verifier` — runs P1-A1 parity test (3-invocation; CRITICAL canary); runs all 5 Phase 1+2 test suites listed in §3 C6; subprocess smoke; full pytest regression
- `impl-critic` — adversarial review for cycles, dropped re-exports, behavior drift in moved functions, hash composition consistency with P2-A1

Expected wall time: ~90-150 min (largest single ticket so far; ~1857-line move + cycle risk).

**P2-A1 lesson applied**: this brief was written by re-reading §6.2 + §5.8 + §4.1 verbatim. Implementer should still cross-check function-list-to-move against the actual PIA file (line numbers from grep above) before coding.
