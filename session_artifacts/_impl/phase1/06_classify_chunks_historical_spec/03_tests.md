# 03_tests.md — impl-tester report for ticket phase1/06_classify_chunks_historical_spec

## Round 2 updates (impl-tester R2)

**Scope**: R2 critic finding — batch path inject-bug test missing.

**Verdict change**: partial -> sufficient (R2 addressed)

### R2 finding summary

The critic (05_critique.md SQ4/R2) found that `_prepare_batch_gen_item` computes
`usable = classified["kept"] + classified["deletable"]` at the Python layer but
passes `"chunk_dir": str(mode_dir)` (the raw mode directory) to the worker job
dict. `_batch_gen_worker.py:81` then passes `--from-cache str(job["chunk_dir"])`
to the analyzer subprocess WITHOUT `--upstream-config-md5` / `--upstream-code-md5`
filter args. The analyzer's default for those flags is empty string = no filter,
meaning it reads ALL `chunk_*.json` in the directory, including historical-md5 chunks.

The Python-layer `usable` variable correctly excludes historical chunks for
bookkeeping/quota math (max_chunks count), but this filtered count is NOT
forwarded to the subprocess as a per-chunk file list or as md5 filter flags.
Max_chunks limits how many chunks the analyzer reads but does not select by md5:
if historical chunks have lower chunk indices, they sort first and are read first.

This violates brief §3 C2 ("any code path that calls equivalent analyzer
execution, the chunk list contains zero historical-bucket chunks").

### Approach taken: Approach A (xfail assertions)

Two `@pytest.mark.xfail(strict=True)` tests added to
`TestBatchPathHistoricalFilterGap`:

1. `test_batch_job_dict_includes_md5_filter_keys` — asserts the job dict includes
   `upstream_config_md5` + `upstream_code_md5` keys. Fails today because neither
   key is present. Will pass once the fix adds these keys.

2. `test_batch_job_chunk_dir_does_not_contain_historical_chunks` — asserts that
   the directory at `job["chunk_dir"]` contains zero historical-md5 chunks.
   Fails today because `chunk_dir` is the raw mode directory with all chunks.
   Will pass once the fix either filters the directory or uses per-chunk paths.

Both tests call `prepare_fn("M14", 1)` directly (captured via
`BatchGenerateManager.__init__` monkeypatching during `create_app`). No threading,
no ProcessPoolExecutor, no analyzer subprocess needed — the contract is the job
dict shape.

### Inject-bug verification log (R2)

For xfail tests, inject-bug discipline works in reverse: the CURRENT production
code IS the bug. Verified both tests fail when `--runxfail` bypasses the marker:

**Test 1 — `test_batch_job_dict_includes_md5_filter_keys`**

```
python -m pytest tests/backend/test_classify_chunks_historical_consumers.py::TestBatchPathHistoricalFilterGap::test_batch_job_dict_includes_md5_filter_keys --runxfail -v
FAILED (1 failed in 0.13s)
AssertionError: REGRESSION (batch path): job dict is missing md5 filter keys:
  ['upstream_config_md5', 'upstream_code_md5'].
Full job keys: ['bet', 'chunk_dir', 'chunk_robot_count', 'chunk_spin_times',
  'classify_dir', 'machine', 'max_chunks', 'mode', 'output_dir', 'paytables_dir',
  'progress_file', 'run_id']
```

**Test 2 — `test_batch_job_chunk_dir_does_not_contain_historical_chunks`**

```
python -m pytest tests/backend/test_classify_chunks_historical_consumers.py::TestBatchPathHistoricalFilterGap::test_batch_job_chunk_dir_does_not_contain_historical_chunks --runxfail -v
FAILED (1 failed in 0.14s)
AssertionError: REGRESSION (batch path): chunk_dir='.../rawdata/M14/mode_1'
  contains 3 historical-md5 chunk(s) that the analyzer subprocess will read
  (no md5 filter is applied). max_chunks=2 limits count but not md5-selectivity.
```

Both tests correctly expose the bug. With xfail markers restored, both show as
`XFAIL` in the normal test run (confirmed: 15 passed, 2 xfailed in 0.56s).

### How the xfail becomes the regression guard

When the fix PR lands:
1. Add `upstream_config_md5` + `upstream_code_md5` to `job` dict in
   `_prepare_batch_gen_item`, and forward them in `_batch_gen_worker.py`
   as `--upstream-config-md5` / `--upstream-code-md5` CLI flags.
2. Remove `@pytest.mark.xfail` from both tests.
3. Both tests will now PASS, becoming permanent regression guards.
4. If the fix is incomplete (job keys present but worker doesn't forward them),
   a separate e2e test would be needed — but the job-dict test covers the first
   half of the fix.

### Net test count

Round 1: 15 tests
Round 2 added: 2 tests (both xfail)
Total: 17 tests (15 passing, 2 xfailed)

---

## Original Round 1 report

## Verdict

**sufficient**

All 5 brief contracts (C1-C5) are covered, with C1 deferred to implementer (docstring, no executable assertion possible). Inject-bug discipline applied to C2 (primary regression guard) and verified end-to-end. 15 new tests, 15 passing, 0 failing.

---

## Test files added

| File | Test count |
|------|-----------|
| `tests/backend/test_classify_chunks_historical_consumers.py` | 15 |

---

## Contract coverage map

| Contract | Tests asserting it |
|----------|-------------------|
| C1 — docstring lists every consumer | Deferred — implementer owns docstring extension; no executable assertion for prose content |
| C2 — historical never feeds default analyzer path | `TestHistoricalNeverFeedsDefaultAnalyzerPath::test_run_generate_report_excludes_historical` (primary), `test_run_generate_report_reads_current_chunks` (complement), `TestClassifyChunksBucketSeparation::test_historical_not_in_kept`, `test_historical_not_in_deletable`, `test_buckets_are_disjoint_mixed_scenario`, `test_parametrized_bucket_sizes[*]` (3 parametrize cases); **R2 batch path (xfail)**: `TestBatchPathHistoricalFilterGap::test_batch_job_dict_includes_md5_filter_keys`, `test_batch_job_chunk_dir_does_not_contain_historical_chunks` |
| C3 — md5-is-tag: historical ≠ auto-deletable | `TestHistoricalIsTagNotDestructionSignal::test_classify_chunks_does_not_delete_historical_files`, `test_check_rawdata_status_does_not_delete_historical_files`, `test_read_only_callers_preserve_historical_file[_classify_chunks]`, `test_read_only_callers_preserve_historical_file[check_rawdata_status]`, `TestAutoCleanupRequiresSpacePressure::test_no_deletion_when_above_target_despite_historical_chunks` |
| C4 — inject-bug TDD | Verified below; `test_run_generate_report_excludes_historical` goes RED with bug, GREEN after revert |
| C5 — no `auto_delete_*` parameter in `check_rawdata_status` | `TestCheckRawdataStatusSignature::test_no_auto_delete_parameter_in_signature`, `test_accepted_parameters_are_read_only_in_intent` |

---

## Inject-bug verification log

### C4 — Primary inject-bug for C2

**Target**: `src/web_console/backend/app.py` line 6845, inside the `else` branch of `_run_generate_report` (the no-md5-filter default path).

**Correct code (baseline)**:
```python
usable_entries = classified["kept"] + classified["deletable"]
```

**Injected bug**:
```python
usable_entries = classified["kept"] + classified["deletable"] + classified["historical"]  # BUG_INJECT
```

**Step 1 — inject**: Applied the mutation above.

**Step 2 — run test → RED**:
```
FAILED tests/backend/test_classify_chunks_historical_consumers.py::TestHistoricalNeverFeedsDefaultAnalyzerPath::test_run_generate_report_excludes_historical
AssertionError: REGRESSION: historical chunk response reached the analyzer.
observed markers: ['CURRENT', 'CURRENT', 'HISTORICAL', 'CURRENT'].
_run_generate_report must not include classified['historical'] in usable_entries
when no md5 filter is active (line 6845).
```

**Step 3 — revert**: Restored original code.

**Step 4 — run test → GREEN**:
```
15 passed in 0.34s
```

**Debugging note**: An initial version of the spy had a logic error — the condition `"_marker" in result.get("response", [{}])[0:1]` checks list membership (is the string `"_marker"` an element of the list?), not dict key presence. This made the spy silently non-operative (always False). Fixed by removing the outer guard and iterating directly over `result.get("response", [])`. The corrected spy correctly captures the HISTORICAL marker when the bug is present.

### C5 — Signature guard

**What goes RED**: Adding `auto_delete_mismatched=False` to `check_rawdata_status`'s parameter list in `app.py` causes `test_no_auto_delete_parameter_in_signature` to fail immediately with:
```
AssertionError: check_rawdata_status must NOT accept any auto_delete_* parameter;
found: ['auto_delete_mismatched'].
```

**What goes RED**: Adding any unexpected parameter (e.g., `force_delete=False`) causes `test_accepted_parameters_are_read_only_in_intent` to fail.

This was not run as a live inject because the existing function signature is already clean — injecting would require modifying the prod function, which risks breaking other tests that call `check_rawdata_status` with keyword arguments.

### C3 — File-deletion guard

**What goes RED**: Adding `hist_chunk.unlink()` inside `_classify_chunks` after building the historical list causes `test_classify_chunks_does_not_delete_historical_files` to fail with:
```
AssertionError: REGRESSION: _classify_chunks deleted the historical chunk!
md5 drift is a classification tag only — no auto-delete.
```

Not run as live inject (trivial to verify structurally — `_classify_chunks` has no `unlink` call).

---

## Coverage explanation: subprocess vs in-process

All 15 tests are **in-process**. The contracts tested here are:
- Function signature introspection (C5) — inherently in-process
- API-layer filtering logic: `_run_generate_report` builds `usable_entries` in-process before calling `pia.post_json` (C2)
- Read-only classification: `_classify_chunks` and `check_rawdata_status` don't spawn subprocesses (C3)

Subprocess-mode behavior (analyzer consuming only matching-md5 chunks from disk) is covered by the existing `tests/backend/test_analyzer_e2e_md5_filter.py` which spawns a real analyzer subprocess.

The boundary between this test file and `test_analyzer_e2e_md5_filter.py`:
- This file: the **filter selection** (which entries from `_classify_chunks` result reach the chunk-path list) — in-process, fast
- `test_analyzer_e2e_md5_filter.py`: the **analyzer subprocess consuming only matching chunks** from disk — subprocess, slow

---

## Open gaps

1. **C1 (docstring)** — Not testable as an executable assertion. Implementer owns the docstring extension. Impl-critic should verify the grep survey was exhaustive.

2. **`_prepare_batch_gen_item` path (line 7225)** — **RESOLVED in R2**. Two xfail tests added: `TestBatchPathHistoricalFilterGap::test_batch_job_dict_includes_md5_filter_keys` and `test_batch_job_chunk_dir_does_not_contain_historical_chunks`. These expose the existing bug (chunk_dir passed without md5 filter to worker) and will become permanent regression guards once the fix PR removes the xfail markers. The gap was worse than originally characterized: the Python-layer `usable` filter is silently discarded at the subprocess boundary.

3. **Md5-filter path** — When `config_md5 + code_md5` are both provided, `_run_generate_report` intentionally includes `classified["historical"]` (user-requested historical report replay). This path is correct behavior and is NOT guarded by our tests; it's the opposite of C2. The brief does not ask for it to be blocked.
