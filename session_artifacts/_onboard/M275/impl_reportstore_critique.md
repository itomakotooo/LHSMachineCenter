# impl-critic: report-store management fix (2026-06-12)

Reviewed: src/web_console/backend/report_index.py (new), tests/backend/test_report_index.py (new),
src/web_console/backend/app.py (diff), src/web_console/backend/reports_retention.py (diff).
Design: session_artifacts/_arch_playtype/REPORT_MGMT_FIX_2026-06-12.md.

---

## REAL-BUG: Batch F2 cleanup is dead code

**File: app.py, lines 9833-9840**

The F2 litter-guard for the batch-generate path is placed AFTER `return {"ok": False, "error": err}`
at line 9831. The condition `if not worker_result.get("ok")` at line 9834 can NEVER be True at
that point — execution only reaches line 9833 when `worker_result.get("ok")` IS truthy (the prior
block already returned for the False case). The batch path's entire F2 cleanup is permanently
unreachable.

Consequence: a failed batch worker leaves its version dir on disk forever (the original defect the
fix was supposed to cure), while the inline generate path IS correctly cleaned up. Both halves of
the system behave differently with no visible indication of the asymmetry.

The fix belongs at the top of the failure arm (line 9824, BEFORE `return {"ok": False, ...}`).

---

## REAL-BUG: active_run_versions guard misses "importing" status

**File: app.py, line 10800**

The reconcile guard for no-summary dirs queries only `status="running"`. The import path inserts
rows with `status="importing"` (line 10613) BEFORE the copytree completes. A concurrent reconcile
that fires between insert and copytree would find the version dir empty (copytree not started) or
partial (copytree in progress) — neither has a summary yet. Both cases pass both guards (not in
active_run_versions, mtime < 1h) — but mtime guard only helps if the import completes within 1h.
The design doc says "running or pending"; the code only checks "running". "importing" is the third
status that creates dirs-without-summaries and is entirely missing from the guard.

---

## REAL-BUG: copytree destination already exists when canonical vdir is present

**File: app.py, reconcile action 4 (path_copy_to_canonical branch)**

The condition for entering the copy branch is: `summary_path.exists()` is False AND
`Path(stored_sf).exists()` is True. `summary_path` is computed as `vdir / "player_impact_summary.json"`
where `vdir` IS the canonical path (`_rr / machine / mode_N / versions / vname`). So `summary_path`
not existing means the canonical vdir either does not exist or exists but has no summary. If vdir
exists but has OTHER files (machine_config.json, progress.jsonl), `shutil.copytree(src, vdir)` will
FAIL immediately with `FileExistsError` because copytree's `dst` must not already exist (Python <
3.8 default; Python >= 3.8 has `dirs_exist_ok=False` by default). The `except Exception` swallows
this silently and logs "copytree: FileExistsError", leaving the entry unrepaired. This is the
exact scenario for the "9 dirs holding only machine_config.json/progress.jsonl" class listed as
live defects.

---

## RISK: append_and_rewrite_latest sets latest = the just-appended entry, not max(created_at)

**File: report_index.py, lines 346-351**

The comment says "entries land in chronological order" and uses the just-appended entry as latest.
This is true for the normal finalize flow but NOT for reconcile (Action 3 via `append_index_entry`)
nor for `_refresh_mode_manifests` (retention rebuild). If reconcile appends an entry for a
historically older report, `append_and_rewrite_latest` would overwrite latest.json with the older
entry. The reconcile function uses its own write path (lines 11110-11128) with a proper `max()` call,
so it does NOT call `append_and_rewrite_latest`. But any future caller that uses `append_and_rewrite_latest`
to replay historical entries (e.g. from a migration script or a second reconcile on a subset) will
silently regress latest.json to an older entry. The design spec says "recomputed, not blind copy"
but the implementation IS a blind copy of the entry being appended. The spec and the code disagree.

---

## RISK: OS lock degraded diagnostic goes only to stderr, not disk (violates feedback_no_silent_swallow)

**File: report_index.py, lines 87-91, 104-108, 118-122**

The precedent in `fresh_slotlab/rawdata_index._cross_process_index_lock` persists the degraded-lock
diagnosis to `<rawdata_root>/_index.json.lock_degraded.json` via `_persist_lock_degraded`. The new
`report_index.py` only prints to stderr (one-shot per mode_dir via `_LOCK_DEGRADED` set). In the
production server context stderr goes to the process log, which is not routinely inspected. If the
OS lock fails silently, the lost-update race (the defect this entire fix targets) reappears with no
observable signal. This contradicts `feedback_no_silent_swallow.md` which requires outcomes to be
persisted to disk, not just stdout/stderr.

---

## RISK: canonical_prefix is computed but never used

**File: app.py, line 10882**

`canonical_prefix = str(versions_dir)` is assigned but never referenced anywhere in the reconcile
function. The actual canonicality check uses `summary_path = vdir / "player_impact_summary.json"`
(which is the canonical path by construction) and compares it to `stored_sf` from the index entry.
The unused variable may be a leftover from a design iteration. It creates no defect but signals
the reconcile was partially redesigned mid-implementation.

---

## RISK: reconcile does NOT handle index entries whose version dir does not exist on disk

**File: app.py, reconcile function**

The scanning loop iterates `versions_dir.iterdir()` (disk-primary). It builds `indexed_by_rv` from
the current index, then for each disk vdir either cleans the dir or updates/appends the index. But
it NEVER iterates `indexed_by_rv` to find entries with no corresponding disk vdir. A run that was
deleted (by prune_versions or manual rm) leaves a dangling index entry pointing to a non-existent
summary. These entries show up in the version picker as reportable rows that 404 when clicked. The
design spec mentions "zombie entry → drop the entry" as an action class (design §F4), but the
implementation only reaches that label when the disk vdir EXISTS but BOTH stored_sf and canonical_sf
are missing files. It never emits `zombie_entry_drop` for the case where the vdir itself is gone.

---

## RISK: reconcile fail-open on list_runs_by_status exception

**File: app.py, lines 10799-10810**

If `store.list_runs_by_status("running")` raises (DB locked, schema mismatch, etc.), the except
block logs to stderr and leaves `active_run_versions` as an empty set. The reconcile then proceeds
with NO active-run protection. A genuine in-progress run's version dir could be deleted. Per the
design spec this MUST be fail-closed: "delete ONLY IF no running/pending run references it". The
safe default on DB failure is to skip ALL no-summary deletes for that run (or abort the whole
reconcile). Currently it silently becomes fail-open.

---

## RISK: mtime comparison uses os.stat(vdir) not summary file age — wrong for in-progress runs

**File: app.py, line 10862**

`vdir.stat().st_mtime` returns the directory's mtime, which updates when any file is added to the
dir. On Windows, directory mtime is only updated when a direct child is created, not on subdirectory
changes. A batch run that creates the dir then stalls before writing machine_config.json will have
a dir mtime from dir creation. A run that creates the dir, writes machine_config.json, then stalls
will have mtime from machine_config.json write. The 1h guard is timezone-safe (both `time.time()`
and `os.stat().st_mtime` are POSIX timestamps), but the semantics of "age" are ambiguous — it is
"dir/file creation age", not "time since the last meaningful activity on this run".

---

## RISK: F2 failure cleanup silently swallows shutil.rmtree errors

**File: app.py, lines 9580-9582, 9595-9597**

Both F2 exception handlers do:
```python
try:
    shutil.rmtree(output_dir, ignore_errors=True)
except Exception:
    pass
```
`ignore_errors=True` already suppresses all rmtree errors internally, and the outer `except Exception: pass` swallows any remaining ones. No diagnostic is written to disk. If cleanup fails (permissions, Windows file handle held open by a spawned subprocess still writing to the dir), the failed dir persists silently and the operator has no way to know why. This violates `feedback_no_silent_swallow.md` — at minimum, log to stderr with the path.

---

## RISK: report_file hardcoded in import DB row even for new-engine reports (app.py L10630)

**File: app.py, line 10630**

The `_import_one` function writes `"report_file": str(dst / "player_impact_report.md")` into the
DB row for every imported version, regardless of whether the .md actually exists. `build_index_entry`
correctly checks `report_md_path.exists()` before emitting the key. After import, the DB row claims
a .md that may not exist; any code path that reads `row["report_file"]` and tries to serve it (line
10169-10179 `report_versions` endpoint) will 404. The reconcile's action 6 ("report_file key drop")
will fix the index.json entry on next run, but the DB row is not touched by reconcile.

---

## TEST GAPS

1. **TestF2FailureHygiene class listed in the docstring but does not exist in the file.** The test
   module's module-level docstring says class 3 is "TestF2FailureHygiene: generate path failure
   leaves no version dir." No such class appears in the file. The F2 generate-path cleanup is
   entirely untested.

2. **No test for the batch-generate F2 path** (which is also dead code per above). Even fixing the
   dead code leaves zero test coverage.

3. **No test for reconcile's no-summary-dir delete when an "importing" run is in flight.** The
   active-run guard is the safety-critical path in reconcile. The test fixtures (`reconcile_app_client`)
   create no in-progress runs; the guard is never exercised.

4. **No test for reconcile action 4 (path_copy_to_canonical or path_rewrite_to_canonical).** The
   entire path-rot repair logic (the stated motivation: 261 worktree-path entries) has zero test
   coverage. The synthetic litter tree in `_build_litter_tree` only creates classes 1, 2, 3, plus
   one valid entry. The copytree-fails-silently bug (finding above) would not be caught.

5. **No cross-process test.** The threading test (`test_concurrent_append_no_lost_entries`) tests
   8 threads in one process. The design doc says the fix targets `ProcessPoolExecutor` workers
   (batch generate). A two-process test using `subprocess` or `multiprocessing.Process` against a
   real `tmp_path` is missing. The OS lock (msvcrt.locking/fcntl) is never actually exercised.

6. **No inject-bug-RED regression test for the locked-writer invariant.** The design doc spec
   requires "inject-bug → red → revert → green". The concurrent test passes under the current
   implementation but would also pass if you replaced `append_and_rewrite_latest` with the OLD
   unlocked append — because threading.Lock alone (without OS lock) prevents the test-level race.
   The test does not prove the OS layer is doing anything.

7. **No test that reconcile is fail-closed when DB is unavailable.** The active-run guard
   fail-open risk has no regression test.

8. **No test for zombie index entries (index entry with no on-disk vdir).** This class of
   stale entry is not in `_build_litter_tree`.

---

## CLAIM VS REALITY GAPS

- Design says "rewrite_latest: newest entry by created_at (recomputed, not blind copy)." The
  `append_and_rewrite_latest` implementation does a blind copy of the just-appended entry (L351).
  `rewrite_latest` (standalone) does use `max()`. The two functions are inconsistent with each
  other and one contradicts the spec.

- Design says F2 "generate + batch: on failure/exception, remove the created version dir." The
  batch path F2 is dead code (REAL-BUG above). The claim is only half-delivered.

- Design says "lock: timeout + stale-lock handling." `LK_LOCK` retries for ~10 seconds then raises
  OSError. The stale-lock case is handled only in the rawdata_index precedent (where it falls
  through to stderr + within-process-only). The new code behaves identically on timeout. However the
  POSIX path uses `fcntl.LOCK_EX` (blocking indefinitely), so the "timeout" claim only applies to
  Windows. On Linux the lock blocks forever if a process crashes holding it (stale lock). The design
  and docstring say "timeout + stale-lock handling" but POSIX has neither.

- Memory file `feedback_no_silent_swallow.md` is cited in the design doc. Two silent swallows
  introduced: (a) F2 cleanup ignores rmtree failures with no disk write; (b) OS lock degraded
  diagnostic goes only to stderr, not disk.

---

## VERDICT: FIX-FIRST

### Required fixes before commit/merge

1. **REAL-BUG**: Move the batch F2 cleanup block to BEFORE the `return {"ok": False, "error": err}`
   line (app.py ~9831). This is the primary class of litter the fix claims to cure for batch jobs.

2. **REAL-BUG**: Add "importing" to the active_run_versions query in reconcile (query both
   `"running"` and `"importing"` statuses). Design doc says "running or pending" — at minimum
   include both; audit which transient statuses create dirs-without-summaries.

3. **REAL-BUG**: Fix the `copytree(Path(stored_sf).parent, vdir)` call to use `dirs_exist_ok=True`
   (Python >= 3.8) or check/delete `vdir` first. Otherwise the most common path-rotation repair
   silently fails when the canonical vdir already exists with partial files.

4. **RISK (fail-open guard)**: On `list_runs_by_status` exception, either (a) abort the no-summary
   delete pass entirely with a logged error, or (b) raise so reconcile returns an error response
   rather than silently proceeding without the safety guard.

5. **MISSING TEST**: Add `TestF2FailureHygiene` class (listed in the module docstring but absent).
   Minimum: generate path fails before writing summary → version dir is deleted; generate path
   writes summary then fails → version dir is KEPT.

### Optional improvements

1. Persist the OS lock degraded diagnostic to disk (mirror `_persist_lock_degraded` from
   `rawdata_index.py`) to satisfy `feedback_no_silent_swallow.md`.

2. Add F2 cleanup failure diagnostic (log to stderr with path + error; remove the outer bare
   `except: pass`).

3. Reconcile: add a post-disk-scan pass over `indexed_by_rv` to detect index entries with no
   corresponding disk vdir (orphaned zombie entries). This is the case described in design §F4
   Action 4 "neither → drop the entry (zombie)" but that branch currently only fires when the vdir
   EXISTS on disk.

4. Fix `append_and_rewrite_latest` to use `max(created_at)` like `rewrite_latest`, or document
   that it only supports the "sequential finalize" use case and prohibit its use for out-of-order
   appends.

5. Add `dirs_exist_ok=True` to the import path's `shutil.copytree` call or verify the destination
   cannot exist before copying (currently assumes a fresh dst, which is only guaranteed when
   `get_run(run_id)` returns None before the insert).

6. Fix the import DB row to not unconditionally stamp `report_file` with a .md path that may not
   exist; mirror `build_index_entry`'s conditional logic.

7. Add a cross-process test (two `multiprocessing.Process` workers each calling
   `append_and_rewrite_latest` on the same mode_dir) to prove the OS lock layer actually works.
