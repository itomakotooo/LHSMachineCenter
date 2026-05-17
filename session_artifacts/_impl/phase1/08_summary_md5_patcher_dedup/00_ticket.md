# Ticket P1-B2 — Consolidate summary md5 patcher (real × 2) (Batch 1c)

> Phase 1 / Batch 1c. Depends on Batch 1a (P1-A2 parity test); cleanly extends P1-B1 (both touch md5-related code paths).

---

## §1 Ticket scope

Two implementations of "fill empty `summary.code_md5` / `summary.config_md5` after analyzer wrote them blank":
- [src/web_console/backend/app.py:6955-6973](src/web_console/backend/app.py:6955) (`_run_generate_report` post-`pia.main()`)
- [slot_designer/core/backend/virtual_analyzer.py:506-558](slot_designer/core/backend/virtual_analyzer.py:506) (`_patch_summary_md5_tags` post-delegate)

Same intent ("real analyzer left empty md5; patch in"). Two impls with cross-referencing comments — textbook duplication.

Files expected to change:
- `fresh_slotlab/summary_md5_patch.py` (new) — canonical `patch_summary_md5(summary_path, md5_lookup_fn) -> None`
- `src/web_console/backend/app.py:6955-6973` — call shared helper
- `slot_designer/core/backend/virtual_analyzer.py:506-558` — call shared helper
- `tests/backend/test_summary_md5_patcher_canonical.py` (new) — regression per §3

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §4` row 2 ("md5 patch into summary")
- `session_artifacts/_arch/03_coupling_audit.md §4.5` — duplicate primitives
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — summary patcher × 2
- Memory `feedback_md5_granularity_and_stamping.md` — both paths must patch (real AND virtual delegate); easy to miss one
- Memory `feedback_no_silent_swallow.md` — patcher failures must not be silent

---

## §3 Contract (testable invariants)

### C1 — Single helper, injectable lookup
`fresh_slotlab/summary_md5_patch.py:patch_summary_md5` accepts an injectable `md5_lookup_fn` (default uses canonical real lookup from P1-B1; virtual injects its local `compute_machine_md5_for_mode`).

### C2 — Both callsites use helper
`app.py:6955-6973` becomes a thin call site. `virtual_analyzer.py:506-558` becomes a thin call site (injecting virtual lookup_fn). No body-level duplication remaining.

### C3 — Per-mode granularity preserved
Helper writes per-mode md5 correctly (per memory `feedback_md5_granularity_and_stamping.md`). Verifiable via the P1-A2 parity test on mode 1 vs mode 2.

### C4 — Empty-md5 detection
Helper detects empty md5 fields (string `""`, missing key, or `None`) and patches them; non-empty values are NOT overwritten. Test asserts both branches.

### C5 — Failure logging
Per memory `feedback_no_silent_swallow.md`: if md5 lookup fails (e.g., machine not in `configs/machines.json`), helper logs the failure with full context (machine, mode, error) — does NOT silently leave summary md5 empty. Test asserts the log path.

### C6 — Inject-bug TDD
Tester: revert the dedup → inject a wrong value into real path patcher → assert the regression test catches the patcher divergence. Document in `03_tests.md`.

---

## §4 Out of scope

- Eliminating the "patch after the fact" pattern (broader analyzer rewrite)
- Changing the md5 schema
- Merging with `_lookup_machine_md5` ticket (P1-B1) — these are separate concerns (lookup vs patch)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores both local patchers.

---

## §6 Risk + rollback notes

**Risk class**: LOW-MEDIUM.

**Dependency**: P1-A2 (parity test), P1-B1 (canonical lookup) — both should be landed first.

**Subprocess mode**: virtual_analyzer.py runs as subprocess. impl-verifier spawns subprocess against M14 mode 1 cached chunk + asserts summary md5 fields populated post-helper call. Per memory `feedback_perf_claim_needs_e2e_event_stream.md`.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — extracts helper + updates 2 callsites
- `impl-tester` — writes regression + inject-bug log; explicitly tests both lookup_fn injection variants

### Wave 2 (parallel)
- `impl-verifier` — runs P1-A2 parity (must stay green); runs full pytest; spawns real + virtual analyzer subprocesses against cached fixtures; asserts md5 fields populated
- `impl-critic` — checks: lookup_fn signature general enough? Is failure logging actually exercised by the test (not just guarded by happy-path)?

Expected wall time: ~30-45 min.
