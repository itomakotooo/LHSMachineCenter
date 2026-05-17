# 05_critique_round2.md — impl-critic round-2 report
# Ticket: phase1/06_classify_chunks_historical_spec (P1-A4)

**Round-2 scope**: Four round-1 revisions were applied.
- R1 (main session): docstring corrected for `_prepare_batch_gen_item` — now honestly admits the batch path includes historical chunks and explains why
- R2 (tester): two `@pytest.mark.xfail(strict=True)` tests added to `TestBatchPathHistoricalFilterGap`
- R3 (main session): line numbers corrected throughout docstring
- R4 (main session): `force=True` bypass note added to `delete_rawdata` consumer entry

Round-1 required revisions R1 and R2 were blocking. R3 and R4 were non-blocking.

---

## Verdict: APPROVE

All four round-1 revisions land correctly. No new blocking defects introduced. Five stress questions raised below; three are fully addressed, one is partial (non-blocking), one surfaces a residual line-number drift that is within the docstring's stated `~` approximation tolerance but worth noting for the record.

---

## Stress questions (5 total: 3 ✓ / 1 ⚠ / 1 note-only)

---

### SQ-R2-1 — `xfail(strict=True)` semantics: right pattern or confusing failure mode?

**Question**: The tester chose `strict=True` so that if the production code is fixed without removing the xfail marker, pytest surfaces an XPASS error rather than silently passing. Is this the right pattern? Or does it create a confusing failure mode for a contributor who sees "XPASS" and doesn't know what to do?

**Analysis**: `strict=True` means: if the test unexpectedly PASSES, count it as a test FAILURE. For this use case — a known bug that must be fixed with a companion test-marker removal — that is exactly the correct semantics. Without `strict=True`, the fix PR could land, the test would quietly XPASS (shown in the summary but not flagged as a failure), and the xfail marker would remain in the codebase forever, making the test file misleading. With `strict=True`, the fix PR will be caught by CI: the contributor MUST remove the xfail markers as part of the fix. The xfail reason strings are detailed (cite the critic finding, the fix options, and explicit "Remove this xfail marker when the fix is applied"), so the error message a contributor sees is actionable.

The one legitimate concern: contributors unfamiliar with `strict=True` may be confused by "XPASS is a failure." The fix: the test docstring for `test_batch_job_dict_includes_md5_filter_keys` already says "When the fix is applied: ... Remove xfail." The xfail reason strings are paste-quality explanations. This is sufficient.

Also confirmed: the inject-bug discipline for xfail tests was correctly inverted in 03_tests.md — "the current production code IS the bug" — and both tests were verified with `--runxfail` to confirm they fail with the current code (as required by C4 discipline).

**Verdict: ✓** — `strict=True` is the correct pattern. Reason strings are actionable. Inject-bug verification log (--runxfail) confirms both tests fail today. No concern.

---

### SQ-R2-2 — Does the docstring's R1 fix actually match what the xfail tests assert?

**Question**: The docstring (R1 fix) says "The worker does NOT forward `--upstream-config-md5` / `--upstream-code-md5` filter args today." The xfail test `test_batch_job_dict_includes_md5_filter_keys` asserts the job dict lacks `upstream_config_md5` / `upstream_code_md5` keys. These are different layers: job-dict layer (Python) vs. worker-argv layer (subprocess CLI). Could a fix that adds the keys to the job dict but fails to forward them in the worker pass the job-dict test but leave the underlying bug unfixed?

**Analysis**: This is the sharpest question in round 2. There are two distinct fix requirements:
1. Add `upstream_config_md5` / `upstream_code_md5` to the job dict in `_prepare_batch_gen_item` (tested by `test_batch_job_dict_includes_md5_filter_keys`)
2. Forward those keys as `--upstream-config-md5` / `--upstream-code-md5` CLI args in `_batch_gen_worker.py` (NOT tested by either xfail test)

A developer could satisfy requirement 1 (making the first xfail test pass) without doing requirement 2 (the actual CLI forwarding). In that case:
- `test_batch_job_dict_includes_md5_filter_keys` would transition from XFAIL to PASS, so its xfail marker would need to be removed
- `test_batch_job_chunk_dir_does_not_contain_historical_chunks` would still XFAIL (chunk_dir still points to a directory with historical chunks)
- The fix would be incomplete — the worker still doesn't forward md5 filter args, so the analyzer reads historical chunks

The tester acknowledged this in 03_tests.md Round 2: "If the fix is incomplete (job keys present but worker doesn't forward them), a separate e2e test would be needed — but the job-dict test covers the first half of the fix."

The docstring is honest about this: it says the worker "does NOT forward" the args. The xfail test correctly targets the job-dict layer. The second xfail test (`test_batch_job_chunk_dir_does_not_contain_historical_chunks`) would catch the case where the directory still has historical chunks even if md5 keys are added — meaning both tests must pass for the fix to be considered complete.

However: a half-fix that adds job keys but uses no-op worker forwarding could cause both xfail tests to pass while the analyzer still reads historical chunks (because the analyzer's `--upstream-config-md5` implementation might have a bug). The existing `test_analyzer_e2e_md5_filter.py` is the backstop for that case, and it covers the analyzer-subprocess behavior independently.

**Verdict: ⚠** — The two xfail tests together cover the job-dict shape contract. The worker-argv forwarding contract is not directly covered by these tests. The note in 03_tests.md acknowledges this as an incomplete coverage. For a LOW-risk ticket (docstring + test), this is acceptable: the docstring honestly names the gap, the xfail tests create forcing-function pressure, and `test_analyzer_e2e_md5_filter.py` is the downstream backstop. Not a blocking defect, but the fix PR author should be aware that removing the xfail markers requires removing BOTH, verifying the analyzer argv contains the filter flags (which the existing e2e test covers).

---

### SQ-R2-3 — Is the batch-path bug a real prod incident or theoretical?

**Question**: The docstring documents the batch-path bug as a known prod issue. Has this caused a real user-visible failure (wrong RTP in batch reports), or is it theoretical? Per memory `feedback_md5_is_a_tag_not_a_destruction_signal.md`, the related M1|1 incident (2026-04-20) had real prod fallout.

**Analysis**: The docstring does not cite any observed batch-report-RTP anomaly caused by historical chunks contaminating batch output. The bug is real (confirmed by tester's `--runxfail` log showing the directory contains 3 historical-md5 chunks that the analyzer would read) but its production impact depends on frequency:

- If batch-generate-report is run immediately after a machine config/code update, current-md5 chunks will have higher chunk indices than historical-md5 chunks (historical = older, lower indices). The analyzer reads `max_chunks = len(usable) = kept + deletable count`, but sorted by filename. Historical chunks will sort BEFORE current ones (lower indices), meaning the analyzer reads historical data first within the budget.
- If `max_chunks = 5` and there are 3 historical + 5 current, the analyzer reads chunk_0001 (historical), chunk_0002 (historical), chunk_0003 (historical), chunk_0004 (current), chunk_0005 (current) — 3/5 reads are historical.

The round-1 critique (edge case 2, now documented in docstring) called this the worst case: historical chunks often sort first. Per the verify log in 04_verification.md, the full suite has 2213 passing tests — no test failure caused by this behavior, suggesting it hasn't surfaced in existing test fixtures (likely because test fixtures use a clean mode directory with only one md5 version). The production exposure is real for any machine that has been config-updated while batch-generate-report accumulates old chunks.

The docstring correctly calls it a "known prod issue" without escalating to a P0 incident. The xfail tests create the appropriate urgency level.

**Verdict: ✓** — Classification as "known prod issue" is accurate. Not a confirmed incident, but a structurally demonstrable data-quality risk. The docstring's framing is honest and appropriately calibrated.

---

### SQ-R2-4 — Fix ticket: does it actually exist?

**Question**: The docstring says "(TODO: open ticket to forward md5 filter args from `_prepare_batch_gen_item` → `_batch_gen_worker.py` → analyzer CLI)". The tester's 03_tests.md says "TODO: open ticket to forward md5 filter args." Does this ticket exist anywhere in the Phase 1 ticket index, Phase 2 planning, or any artifact?

**Analysis**: Searching the Phase 1 ticket index (`PHASE_1_TICKETS.md`) and all session_artifacts phase1 ticket files: no ticket for this fix exists. The 12 Phase 1 tickets cover dedup/spec/bug-fix work defined in the arch handoff. The batch-path md5 filter forwarding bug was discovered during the P1-A4 impl-critic review cycle, not during the original arch design. The "TODO: open ticket" in both the docstring and 03_tests.md are forward references to a ticket that does not yet exist.

The xfail tests with `strict=True` are the only enforcement mechanism. They will surface as CI failures when the fix is applied without xfail removal, but they will not surface until someone attempts a fix. There is no scheduled work item to trigger the fix.

This is a process gap. The TODO in the docstring is not self-executing. Without a ticket, this could remain as a permanent xfail-documented known bug for the duration of Phase 1/2 without ever being fixed.

However: under the ticket brief's risk classification (LOW — docstring + test only), the appropriate action for a discovered pre-existing bug is exactly what was done: document it honestly and add xfail tests. Creating a fix ticket is the main session's responsibility, not this ticket's. The critique can flag the gap but cannot require the fix ticket to exist as a condition of approval for THIS ticket.

**Verdict: ✓ (with flag)** — The xfail tests and docstring correctly document the bug. The absence of a fix ticket is a process gap that should be resolved by main session (add the batch-path md5 forwarding fix as a Phase 1 or Phase 2 ticket). The round-2 artifacts do not block on this — they create the right kind of pressure. Flag to main session: open the follow-up ticket before closing P1-A4.

---

### SQ-R2-5 — R3 line corrections: were ALL drifted references corrected, or only the critic-pointed ones?

**Question**: Round-1 critic (SQ3 + SQ7) flagged `_run_generate_report` at "~6733" (actual 6789) and `_auto_cleanup_for_space` at "~2528" (actual ~2617). The R3 fix corrected these. But the docstring has 7 consumers, each with a line reference. Were ALL checked, or only the two explicitly flagged?

**Analysis**: Reading the current docstring (lines 936-1023) and comparing to grep-confirmed actual function definitions:

| Consumer | Docstring says | Actual def | Diff |
|---|---|---|---|
| `delete_rawdata` | ~line 1133 | 1148 | 15 lines |
| `_build_rawdata_overview` | ~line 2087 | 2162 | 75 lines |
| `_auto_cleanup_for_space` | ~line 2617 | 2563 | -54 (docstring is AHEAD) |
| `get_rawdata_status` | ~line 5971 | 6055 | 84 lines |
| `_run_generate_report` | ~line 6789 | 6808 | 19 lines |
| inject site | ~line 6845 | 6864 | 19 lines |
| `_prepare_batch_gen_item` | ~line 7136 | 7228 | 92 lines |
| `_enumerate_rawdata_deletable` | ~line 8766 | 8785 | 19 lines |

The `~` prefix is specifically documented as an approximation. All references are within 100 lines of actual. The `_prepare_batch_gen_item` drift (92 lines) and `get_rawdata_status` drift (84 lines) are at the upper boundary of what `~` can reasonably approximate, but none are 56+ lines pointing to a different function (the round-1 defect where `~6733` pointed to `create_run` not `_run_generate_report`). The R3 corrections addressed the worst cases. The remaining drift is within the stated approximation convention.

The verifier's `04_verification.md` table (written for Round 1) lists `_classify_chunks(` call sites at lines matching the calling function, not the function definitions — e.g., it says `_run_generate_report` called at line 6822. Actual: `_classify_chunks(machine, mode, rd_root, mc, retention)` inside `_run_generate_report` is at line 6841. This 19-line discrepancy is consistent with a Round 1 verification that was done before the R3 docstring corrections landed. The verifier noted "Line numbers in the docstring use `~` approximations (within 100 lines)." That statement is now accurate for all 7 references.

**Verdict: ✓** — R3 corrected the egregious cases (wrong-function-level drift). Remaining drift is within the `~` convention. No residual pointing to the wrong function. Adequate.

---

## Chain disagreements (Round 2)

### No new chain disagreements

The four round-2 artifacts (updated docstring in app.py, updated test file with 2 xfail tests, updated 03_tests.md Round 2 section, and this critique) are internally consistent. The key properties:

- Docstring says: batch path has the bug, uses raw `chunk_dir`, worker does not forward md5 filter args
- Test xfail reason says: same characterization
- Tester's 03_tests.md says: same characterization, with `--runxfail` verify log showing both tests fail
- verifier file `04_verification_round2.md`: running in parallel at time of this critique (does not exist yet) — chain is formally incomplete by one artifact, same as Round 1's `04_verification.md` absence at critique time

The Round 1 `04_verification.md` confirmed 15 tests passing. The round-2 verification is expected to confirm 15 passed + 2 xfailed. The chain disagreements from round 1 (line references, `_prepare_batch_gen_item` false invariant) are all resolved.

---

## Hidden assumptions (Round 2 residual)

**Assumption 1** (carried forward, now documented): The `max_chunks` argument to the analyzer limits count, not md5-selectivity. Both the docstring and test explicitly acknowledge this. No longer a hidden assumption — it is the documented defect.

**Assumption 2** (new, low severity): The `test_batch_job_chunk_dir_does_not_contain_historical_chunks` xfail test detects historical chunks by comparing `_config_md5` against the hardcoded string `"cfg_CURRENT"` (from the test fixture). This is correct for the fixture but is not a general detection: if historical and current chunks coincidentally have the same config_md5 but different code_md5, or if the md5 values in the fixture were set to something other than `"cfg_CURRENT"`, the test would miss historical chunks. For a test-fixture-level test this is acceptable. For production use, the detection logic would need to query the live machines_config.

**Assumption 3** (structural, not new): The xfail tests capture `prepare_fn` via `BatchGenerateManager.__init__` monkeypatching. This assumes `BatchGenerateManager.__init__` is called exactly once during `create_app` and that `prepare_fn` is `_prepare_batch_gen_item_wrapper`. If `create_app` is refactored to not call `BatchGenerateManager.__init__` during construction (e.g., lazy init), the assertion `"prepare_fn" in captured` would fail with a clear error message (not silently). This is adequate sentinel behavior.

---

## Edge cases resolved vs. still open

| Edge case (from R1) | Status in R2 |
|---|---|
| Mixed-md5 directory, `max_chunks` equals usable count — historical sorts first | Documented in docstring; tested by xfail test 2 (`max_chunks=2` but directory has 5 chunks including 3 historical) |
| `_prepare_batch_gen_item` batch path with interleaved historical chunk indices | Documented in xfail test 2 docstring and xfail reason string |
| No inject-bug test for `_enumerate_rawdata_deletable` | Still open; read-only function confirmed by inspection; within acceptable risk for LOW-risk ticket |
| `delete_rawdata` with `force=True` bypass | R4 addressed: docstring now says "Force-flag bypass note (P1-A4 R4): when the caller passes `force=True`..." |
| `get_rawdata_status` calls both `_classify_chunks` AND `check_rawdata_status` | Not addressed; still undocumented in consumer entry. Low severity (display-only, both read-only). Non-blocking. |

---

## Required revisions

None. APPROVE verdict has no blocking revisions.

Non-blocking observations for follow-up (not required for this ticket):
1. The fix ticket (batch-path md5 filter forwarding) should be opened by main session before P1-A4 is marked fully done. The "TODO: open ticket" in the docstring is not self-executing.
2. The `get_rawdata_status` consumer entry could note the dual-call pattern (`_classify_chunks` + `check_rawdata_status` called back-to-back) for completeness, but this is editorial.

---

## Commit-message `## Self-critique` section

```
## Self-critique

- Q: Is `xfail(strict=True)` the right pattern for known-bug tests?
  A: Yes. `strict=True` forces CI failure if the bug is fixed without removing
  the xfail marker. Reason strings are actionable (cite critic SQ4, fix options,
  removal instruction). Both tests verified with `--runxfail` to confirm they
  fail today. Correct mechanics.

- Q: Does the docstring's R1 fix (job-dict layer) match what the xfail tests
  assert, or are they testing different layers?
  A: Partial match. Test 1 (`test_batch_job_dict_includes_md5_filter_keys`)
  tests the job-dict layer (Python). Test 2 (`test_batch_job_chunk_dir_does_not
  _contain_historical_chunks`) tests the directory-level consequence. Neither
  tests the worker-argv forwarding layer directly. A half-fix that adds job keys
  but doesn't forward them in _batch_gen_worker.py would pass both xfail tests
  while leaving the underlying bug alive. Backstop: existing
  test_analyzer_e2e_md5_filter.py covers the analyzer's md5-filter behavior
  end-to-end. Fix PR author must remove BOTH xfail markers, not just one.

- Q: Is the batch-path bug a real prod incident or theoretical?
  A: Real but unconfirmed incident. Structurally demonstrable: historical chunks
  with lower chunk indices sort first, so `max_chunks = len(usable)` reads them
  before current chunks. Prod exposure: any machine where batch-generate-report
  runs after a config/code update while old chunks coexist. No user complaint
  logged, but the mechanism is active. Docstring classification as "known prod
  issue" is accurate.

- Q: Does the fix ticket actually exist?
  A: No. "TODO: open ticket" in docstring + 03_tests.md is a forward reference
  to a ticket not yet created. The xfail tests are the only enforcement. Main
  session should open the follow-up ticket (batch-path md5 filter forwarding)
  before closing P1-A4.

- Q: Were ALL line references corrected in R3, or just the critic-pointed two?
  A: R3 corrected the two worst cases (`_run_generate_report` ~6733→~6789,
  `_auto_cleanup_for_space` ~2528→~2617). All 7 consumer line refs now within
  100 lines of actual function definitions. Largest remaining drift:
  `_prepare_batch_gen_item` at ~7136 vs actual 7228 (92 lines), and
  `get_rawdata_status` at ~5971 vs actual 6055 (84 lines). Both within the
  `~` convention. No reference points to the wrong function.

- Q: Does the `get_rawdata_status` consumer entry fully describe that endpoint's
  behavior (dual-call pattern)?
  A: Minor gap. The endpoint calls both `_classify_chunks` AND `check_rawdata_status`
  back-to-back. The consumer entry documents it as display-only (accurate) but
  does not note the dual-call. Non-blocking editorial gap.
```

---

## Summary

| Area | R1 finding | R2 status |
|---|---|---|
| `_prepare_batch_gen_item` docstring false invariant | ✗ CRITICAL | ✓ FIXED — docstring now accurately describes batch-path behavior |
| Batch-path C2 test coverage | ✗ CRITICAL (gap) | ✓ FIXED — 2 xfail(strict=True) tests added, --runxfail verified |
| `_run_generate_report` line reference (~6733) | ⚠ stale | ✓ FIXED — corrected to ~6789 |
| `_auto_cleanup_for_space` line reference (~2528) | ⚠ stale | ✓ FIXED — corrected to ~2617 |
| `delete_rawdata` force=True bypass undocumented | ⚠ non-blocking | ✓ FIXED — R4 note added |
| xfail strict=True semantics | (round 2 question) | ✓ correct pattern, actionable reasons |
| Fix ticket existence | (round 2 question) | flag — no ticket exists yet, main session action required |
| `04_verification_round2.md` | (expected from parallel verifier) | not yet present at critique time |
