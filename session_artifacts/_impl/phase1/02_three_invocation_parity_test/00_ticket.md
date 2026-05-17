# Ticket P1-A1 — 3-invocation-style parity test (Batch 1a, BLOCKING)

> Phase 1 / Batch 1a. Establishes baseline contract BEFORE any dedup work touches the analyzer or backend; the parity test must exist so later dedups (P1-B1 / P1-B2 / P1-B5) can prove they didn't regress it.

---

## §1 Ticket scope

Write a test that runs all three analyzer invocation styles against the same cached chunk set and asserts they produce byte-identical summary outputs (after stripping nondeterministic fields like run_id and timestamps). No code change — test only.

The three invocation styles per `01_pipeline_map.md §5 Q1`:
- **(a) subprocess via** `RunManager.start_run` at [app.py:4739](src/web_console/backend/app.py:4739) (used by `POST /api/runs:6633`)
- **(b) subprocess via** `BatchRunManager:3160+` per-item
- **(c) in-process** via `_run_generate_report:6700` (imports `pia` module + monkey-patches `pia.post_json:6873`, `sys.argv:6925-6926`, `os._exit:6874-6875`)

Files expected to change:
- `tests/integration/test_analyzer_three_invocation_parity.py` (new)

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §5 Q1` — flags the implicit contract
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — pre-blocker #1
- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.1` — Phase 1 foundation
- Memory `user_testing_machine.md` — M14 mode 1 is validation surface; use it as the fixture

---

## §3 Contract (testable invariants)

### C1 — Common fixture
A single M14 mode 1 cached chunk set (per memory `feedback_no_proactive_fetch.md`: use existing cache, don't fetch) is the input for all three runs.

### C2 — Run all three styles
The test exercises:
- Path (a): spawn `RunManager`-style subprocess against the fixture (or simulate the equivalent CLI invocation)
- Path (b): exercise `BatchRunManager` per-item subprocess path (single-item batch is fine)
- Path (c): call `_run_generate_report` in-process

### C3 — Summary equivalence
After stripping nondeterministic fields (`run_id`, `report_id`, timestamps, file mtimes), the three summaries must agree on:
- `summary.rtp.point_pct` (byte-identical)
- `summary.code_md5`, `summary.config_md5` (byte-identical)
- `summary.analyzer_version` (byte-identical)
- `player_impact.payout_ids_top20` list (same order, same hit_counts, same rtp_pp values)

### C4 — Inject-bug TDD
Tester proves the parity test catches regression: temporarily inject a divergent CLI flag into path (a) only (e.g., drop `--target-halfwidth-pp`) → assert path (a)'s summary diverges from (b)/(c) on `summary.sampling.achieved_halfwidth_pp` → test must go red. Revert → test green. Document in `03_tests.md`.

### C5 — Subprocess-mode coverage
Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: paths (a) and (b) must actually spawn real subprocesses against the real fixture, not stub-patched. Path (c) runs in-process.

---

## §4 Out of scope

- Unifying the three paths into one (separate refactor, post-Phase-1)
- Removing the monkey-patches in path (c) (separate concern)
- Testing alternative machines (M14 mode 1 only; M37 etc. follow in later test additions if needed)
- Performance benchmarking the three paths

---

## §5 Rollback path

Single commit. `git revert <sha>` deletes the test file. No dependencies.

---

## §6 Risk + rollback notes

**Risk class**: LOW (test-only). No prod code changes.

**Existing tests affected**: none expected. If the new parity test fails on `collab/dev` baseline (i.e., the three paths ARE divergent today), that's a real finding — flag in `04_verification.md`, do NOT silently weaken the test. Per memory `feedback_adversarial_self_review.md`: moving goalposts is a critic-flag offense.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — N/A for this ticket (test-only); skip or have implementer just stage the fixture
- `impl-tester` — primary author of the test file + `03_tests.md` with inject-bug log

### Wave 2 (parallel)
- `impl-verifier` — runs the new test 3× to confirm flakiness-free; runs full pytest suite
- `impl-critic` — checks: did tester cover all 3 paths? Is inject-bug step rigorous? Are the stripped-field choices justified (no over-stripping that hides real divergence)?

Expected wall time: ~30-45 min.
