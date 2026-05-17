# Ticket P1-A4 — `_classify_chunks` historical semantics spec'd (Batch 1b)

> Phase 1 / Batch 1b. Extends an already-good docstring to be exhaustive about consumers, plus adds a guard test asserting historical chunks never enter analyzer execution paths.

---

## §1 Ticket scope

[app.py:_classify_chunks:889-1039](src/web_console/backend/app.py:889) already has a strong docstring (lines 896-922) clarifying "tag for display + analyzer filtering, NOT a deletion decision". This ticket (a) extends the docstring to enumerate ALL known consumers and their semantics, (b) adds a regression test asserting historical-bucket chunks never appear as analyzer input.

Files expected to change:
- `src/web_console/backend/app.py:889-1039` — extend `_classify_chunks` docstring
- `tests/backend/test_classify_chunks_historical_consumers.py` (new)

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §5 Q7` — flags unverified consumer pattern
- Memory `feedback_md5_is_a_tag_not_a_destruction_signal.md` — version tag is for classification + filtering, not destruction; auto-delete from md5 drift caused the 2026-04-20 M1|1 incident
- Memory `feedback_enumerate_safety_paths.md` — every consumer path must be guarded

---

## §3 Contract (testable invariants)

### C1 — Docstring lists every consumer
Extended docstring enumerates each known consumer of the kept / deletable / historical buckets, with file:line and purpose:
- `_run_generate_report:6733` — uses `kept` for in-process analyzer replay; NEVER passes `historical`
- `_auto_cleanup_for_space:2455+` — uses `deletable` + `historical` for mtime-based eviction (locked pairs skipped)
- Per-version DELETE endpoint at `:6042-6162` — uses explicit version, not bucket
- UI display routes (which `/api/...` endpoints return classification labels) — list them

If a consumer is found that doesn't match these patterns → flag in `02_implementation.md` for separate ticket review (might be a real bug).

### C2 — Historical-never-replays test
Regression test asserts: for any code path that calls `pia.main()` / `_run_generate_report()` / equivalent analyzer execution with a chunk list, the chunk list contains zero historical-bucket chunks. Verifiable by mocking `_classify_chunks` to return a synthetic historical entry → assert it's filtered before reaching analyzer.

### C3 — md5-is-tag invariant
Per memory `feedback_md5_is_a_tag_not_a_destruction_signal.md`: test asserts NO code path interprets historical bucket as "auto-deletable" (separate from the deletable bucket). Deletion always goes through `_auto_cleanup_for_space` or explicit per-version DELETE.

### C4 — Inject-bug TDD
Tester: temporarily modify `_run_generate_report:6733` to include historical chunks → assert C2 test goes red. Revert → green. Document in `03_tests.md`.

### C5 — No `auto_delete_mismatched` revival
Per memory `feedback_md5_is_a_tag_not_a_destruction_signal.md`: check `check_rawdata_status` does NOT accept any `auto_delete_*` parameter. Test asserts function signature; revival is a critic-flag offense.

---

## §4 Out of scope

- Renaming `historical` bucket (per memory — would be a separate ticket if needed)
- Modifying `_auto_cleanup_for_space` policy
- Adding new DELETE endpoints

---

## §5 Rollback path

Single commit. `git revert <sha>` removes the docstring extension + test.

---

## §6 Risk + rollback notes

**Risk class**: LOW (docstring + test only; no behavior change).

**Existing tests affected**: none expected. If the test fails on baseline (an actual consumer is passing historical to analyzer), that's a real bug — flag, escalate.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — extends docstring; surveys consumers via grep + reads each callsite
- `impl-tester` — writes the regression test + inject-bug verification

### Wave 2 (parallel)
- `impl-verifier` — runs the regression test, runs full pytest, checks docstring covers actual grep results
- `impl-critic` — checks: was the consumer survey exhaustive? Did tester actually grep for ALL invocations of analyzer execution, not just `_run_generate_report`?

Expected wall time: ~30-45 min.
