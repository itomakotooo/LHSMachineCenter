# 04_verification_round2.md - impl-verifier round-2 report

Ticket: P1-A4 - _classify_chunks historical semantics
Phase: phase1 / 06_classify_chunks_historical_spec
Verifier round: 2
Date: 2026-05-18

---

## Verdict: PASS

All round-2 checks passed. R1 (docstring), R2 (xfail tests), R3 (line numbers), and R4 (force-flag bypass) verified below. No regressions introduced by this ticket.

---

## Check 1 - R2 xfail tests: 15 pass + 2 xfail

Command:
  python -m pytest tests/backend/test_classify_chunks_historical_consumers.py -v

Observed (tail):
  TestBatchPathHistoricalFilterGap::test_batch_job_dict_includes_md5_filter_keys XFAIL
  TestBatchPathHistoricalFilterGap::test_batch_job_chunk_dir_does_not_contain_historical_chunks XFAIL
  15 passed, 2 xfailed in 0.57s

Verdict: PASS. 15 pass + 2 xfail. Not xpass. Matches tester R2 spec exactly.

---

## Check 2 - R2 xfail strict=True: both tests fail when marker bypassed

Command:
  python -m pytest ...::TestBatchPathHistoricalFilterGap::test_batch_job_dict_includes_md5_filter_keys
                   ...::TestBatchPathHistoricalFilterGap::test_batch_job_chunk_dir_does_not_contain_historical_chunks
                   --runxfail -v

Observed (rc=1):
  FAILED test_batch_job_dict_includes_md5_filter_keys
    AssertionError: REGRESSION (batch path): job dict is missing md5 filter keys:
    [upstream_config_md5, upstream_code_md5].
    Full job keys: [bet, chunk_dir, chunk_robot_count, chunk_spin_times,
    classify_dir, machine, max_chunks, mode, output_dir, paytables_dir,
    progress_file, run_id]

  FAILED test_batch_job_chunk_dir_does_not_contain_historical_chunks
    AssertionError: REGRESSION (batch path): chunk_dir=.../rawdata/M14/mode_1
    contains 3 historical-md5 chunk(s) that the analyzer subprocess will read
    (no md5 filter is applied). max_chunks=2 limits count but not md5-selectivity.

  2 failed in 0.19s

Verdict: PASS. Both tests fail (rc=1) when bypassed. Bugs they expose are real.
strict=True confirmed at lines 881 and 925 of the test file. When the fix lands
and markers are removed, any regression restoring the old behavior will fail the
suite - the guard is live.

---

## Check 3 - R1 docstring honesty about batch path

Source: src/web_console/backend/app.py lines 997-1014 (_prepare_batch_gen_item entry).

Verified content (verbatim from lines 997-1014):
  Python-level filter computes usable = classified[kept] + classified[deletable]
  for bookkeeping / quota math only. The actual analyzer subprocess input is the
  raw chunk_dir (mode directory) passed to the batch worker
  (scripts/_batch_gen_worker.py) as --from-cache <chunk_dir>.
  The worker does NOT forward --upstream-config-md5 / --upstream-code-md5 filter
  args today, so the analyzer subprocess defaults to no filter and reads ALL
  chunk_*.json in the directory - INCLUDING historical chunks.
  The Python usable filter does NOT propagate to the subprocess.
  This is the P1-A4 round-2 critic finding (R1) and a known prod issue requiring
  a separate fix ticket. The regression test includes an xfail-marked test that
  asserts the future-correct behavior; flip to non-xfail when the bug is fixed.

Verdict: PASS. The original false claim (historical chunks are NEVER included) has
been replaced with accurate description of actual behavior. The docstring no longer
canonizes a false invariant. All elements the critic R1 required are present.

---

## Check 4 - R3 line number corrections

Actual line numbers confirmed by grep on current file:

  Function                    Docstring says   Actual line   Delta   Old value (pre-R3)
  _run_generate_report        ~line 6789        6808          +19     6733 (wrong fn)
  inject site usable_entries  ~line 6845        6864          +19     6845
  _auto_cleanup_for_space     ~line 2617        2563          -54     2528
  _enumerate_rawdata_deletable ~line 8766        8785          +19     8713

All four references updated from old wrong values to R3 targets. Critical fix:
_run_generate_report previously pointed to 6733 (inside create_run, a different
function entirely). It now points to 6789, within 19 lines of the actual definition
at 6808 - same function, within the tilde approximation. All references now point
to the correct functions.

Verdict: PASS. R3 corrections applied. Navigation value restored; no reference
points to a wrong function.

---

## Check 5 - R4 force-flag bypass note in delete_rawdata

Docstring location: src/web_console/backend/app.py lines 963-967.

Docstring says:
  Force-flag bypass note (P1-A4 R4): when the caller passes force=True the
  function takes the shutil.rmtree path (whole mode directory) - _classify_chunks
  is NOT consulted at all. The force path is operator-explicit and removes the
  entire (machine, mode) tree including all three buckets.

Code confirmation: force=True branch at line 1178 calls shutil.rmtree(target,
ignore_errors=True) at line 1184. _classify_chunks is not called in this branch.
Docstring is accurate.

Verdict: PASS. R4 note present and accurate.

---

## Full pytest regression suite

Command:
  python -m pytest tests/backend/ tests/integration/ -v --tb=short -q

Result: 2 failed, 2236 passed, 23 skipped, 2 xfailed in 124.59s

Failures (both pre-existing, unrelated to P1-A4):

1. tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split
   Error: FileNotFoundError: rawdata/M31/mode_1/chunk_0001.json
   This is an environment fixture gap in this worktree; M31 rawdata not present.
   Git log for this test file shows only commits predating P1-A4 (latest: 284fd19).

2. tests/backend/test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess
   Flaky: FAILED in full-suite run, PASSED when run in isolation.
   Test-ordering interaction. Unrelated to _classify_chunks historical semantics.

Verdict: PASS. No regressions introduced by this ticket.

---

## Subprocess verification

P1-A4 is docstring-only + in-process tests (no behavior change). The xfail tests
assert the job dict shape (in-process contract). Subprocess behavior of the batch
analyzer reading chunks is covered by the pre-existing
tests/backend/test_analyzer_e2e_md5_filter.py.

Subprocess verified: n/a (docstring + test-only ticket, no behavior change)

Frontend verified: n/a (no frontend changes)

md5 invariants: n/a (no changes to hash composition or cache write paths)

---

## Summary table

  Check                                           Verdict
  R2: 15 pass + 2 xfail                          PASS
  R2: strict=True both fail under --runxfail      PASS
  R1: docstring honesty - batch path accurate     PASS
  R3: line number corrections applied             PASS
  R4: force=True bypass documented                PASS
  Full pytest suite: no new regressions           PASS

Overall verdict: PASS
