# Ticket P1-A2 — 3 summary md5 writers parity test (Batch 1a, BLOCKING)

> Phase 1 / Batch 1a. Establishes baseline md5-writer parity BEFORE dedup (P1-B1 / P1-B2) collapses the three writers; the test must exist so collapse can be proven not to regress agreement.

---

## §1 Ticket scope

Write a test asserting all three `summary.code_md5` / `summary.config_md5` writers produce identical values for the same `(machine, mode)`. No code change — test only.

Three writers per `01_pipeline_map.md §5 Q3`:
- **(α) analyzer inline** — `_lookup_machine_md5:2163-2184` in [player_impact_analyzer.py](fresh_slotlab/player_impact_analyzer.py:2163), reads `configs/machines.json` and writes md5 fields inline during `main()`
- **(β) backend post-patch** — `_run_generate_report:6955-6973` in [app.py](src/web_console/backend/app.py:6955) patches empty md5 after `pia.main()`
- **(γ) virtual post-delegate** — `_patch_summary_md5_tags:506-558` in [virtual_analyzer.py](slot_designer/core/backend/virtual_analyzer.py:506) patches after delegate returns

Files expected to change:
- `tests/backend/test_summary_md5_writer_parity.py` (new)

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §5 Q3` — three writers, agreement unproven
- `session_artifacts/_arch/03_coupling_audit.md §4.5` — md5 patcher duplication
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — pre-blocker #2
- Memory `feedback_md5_granularity_and_stamping.md` — per-mode md5 must be granular AND virtual delegate path must be patched
- Memory `feedback_no_proactive_fetch.md` — use cached fixtures

---

## §3 Contract (testable invariants)

### C1 — Three-writer harness
The test invokes paths α, β, γ on the same `(machine, mode)`. Each writer's resulting `(summary.code_md5, summary.config_md5)` tuple is captured.

### C2 — Agreement
For M14 mode 1: `md5_α == md5_β == md5_γ` (byte-identical strings).

### C3 — Per-mode granularity
Run the test on M14 with **mode 1 AND mode 2** (if cached chunks exist for both). Per memory `feedback_md5_granularity_and_stamping.md`, per-mode md5 must NOT collapse modes together. Test asserts mode 1's md5 ≠ mode 2's md5 (different modes have different weights).

### C4 — Virtual path coverage
Per memory `feedback_md5_granularity_and_stamping.md`: virtual delegate path's md5 must be filled (not left empty). Test asserts γ's output is non-empty for a virtual M15 (or any machine with virtual spec); regression on the 2026-04-XX "未标记" issue.

### C5 — Inject-bug TDD
Tester injects a divergent `_lookup_machine_md5` (e.g., return wrong machine's md5) into one path → assert test catches divergence. Document in `03_tests.md`.

---

## §4 Out of scope

- Collapsing the three writers into one (that's P1-B1 + P1-B2)
- Changing md5 algorithm (per `04_v5 §4 hash composition unchanged`)
- Testing every machine (M14 + one virtual machine suffices for parity check)

---

## §5 Rollback path

Single commit. `git revert <sha>` deletes the test file.

---

## §6 Risk + rollback notes

**Risk class**: LOW (test-only).

**Existing tests affected**: none expected. If the test fails on baseline (writers actually disagree today), that's a real finding — flag in `04_verification.md`, escalate to main session. Possibly indicates an existing md5 bug not yet caught.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-tester` — primary author of test file + `03_tests.md` with inject-bug log

### Wave 2 (parallel)
- `impl-verifier` — runs new test 3× for flakiness check; runs full pytest suite; verifies test exercises subprocess path γ (per memory `feedback_perf_claim_needs_e2e_event_stream.md`)
- `impl-critic` — checks: are all 3 writer paths really exercised? Is per-mode granularity checked? Is the virtual-path check meaningful (uses a real virtual fixture)?

Expected wall time: ~25-40 min.
