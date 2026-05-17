# 04_verification.md — P1-A4 `_classify_chunks` historical semantics

## Verdict: PASS

---

## Pytest: new test file

Command:
```
python -m pytest tests/backend/test_classify_chunks_historical_consumers.py -v
```

Result: **15 passed in 0.34s**

All 15 tests pass on the current branch.

---

## Pytest: full backend suite

Command:
```
python -m pytest tests/backend/ --tb=short -q
```

Result: **2213 passed, 1 failed (pre-existing), 23 skipped in ~102s**

The 1 failure is `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` — caused by a missing M31 mode 1 fixture file not present in this worktree. The test has no `@pytest.mark.skipif` guard for the missing file. `git diff HEAD -- tests/backend/test_analyzer_st_split.py` shows zero diff; this ticket did not touch that file. Pre-existing issue.

A second apparent failure (`test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess`) appeared in the first full-suite run but passes when run in isolation and in a second run — this is pre-existing intermittent flakiness from StubProcess thread timing in the full suite. Not caused by this ticket.

Baseline escalation check (per escalation rules): `test_analyzer_st_split.py` is flagged as a baseline regression guard. The failure is due to missing fixture data in the worktree, not code regression. No code in the ticket scope touches this path.

---

## Pytest: integration suite

Command:
```
python -m pytest tests/integration/ -q --tb=short
```

Result: **23 passed in 20.49s** — clean.

---

## Docstring extension verification (brief §3 C1)

Location: `src/web_console/backend/app.py` lines 928-1016 (within `_classify_chunks` docstring).

Grep for all `_classify_chunks(` call sites (excluding definition):

| Line | Enclosing function | Docstring entry |
|------|-------------------|----------------|
| 1222 | `delete_rawdata` | Deletion consumer, `~line 1133` |
| 2176 | `_build_rawdata_overview` | Display consumer, `~line 2087` |
| 2617 | `_auto_cleanup_for_space` | Deletion consumer, `~line 2528` |
| 6060 | `get_rawdata_status` | Display consumer, `~line 5971` |
| 6822 | `_run_generate_report` | Analyzer-input consumer, `~line 6733` |
| 7225 | `_prepare_batch_gen_item` | Analyzer-input consumer, `~line 7136` |
| 8802 | `_enumerate_rawdata_deletable` | Deletion consumer, `~line 8713` |

All 7 call sites confirmed present in code. All 7 documented in the docstring. Line numbers in the docstring use `~` approximations (within 100 lines); all match the correct enclosing function.

The docstring also includes the per-version DELETE endpoint (~line 6042-6162) as an "out-of-scope non-consumer" (documented correctly — it does NOT call `_classify_chunks`).

**Docstring extension verified: YES**

---

## 7th consumer confirmation (brief §3 C1 note)

`_enumerate_rawdata_deletable` exists at line 8766 (definition), called at line 8802 in its own body. Confirmed real function, not a phantom reference.

grep command:
```
grep -n "def _enumerate_rawdata_deletable" src/web_console/backend/app.py
```
Output: `8766:    def _enumerate_rawdata_deletable(`

**7th consumer confirmed real: YES**

---

## Inject-bug spot-check (brief §3 C4)

Target: `src/web_console/backend/app.py` line 6845, the `else` branch of `_run_generate_report`.

Baseline code:
```python
usable_entries = classified["kept"] + classified["deletable"]
```

**Step 1 — inject:**
```python
usable_entries = classified["kept"] + classified["deletable"] + classified["historical"]  # BUG_INJECT
```

**Step 2 — test result (RED):**
```
FAILED tests/backend/test_classify_chunks_historical_consumers.py::TestHistoricalNeverFeedsDefaultAnalyzerPath::test_run_generate_report_excludes_historical
AssertionError: REGRESSION: historical chunk response reached the analyzer.
observed markers: ['CURRENT', 'CURRENT', 'HISTORICAL', 'CURRENT'].
_run_generate_report must not include classified['historical'] in usable_entries
when no md5 filter is active (line 6845).
```

**Step 3 — revert baseline code.**

**Step 4 — test result (GREEN):**
```
15 passed in 0.31s
```

**Inject-bug spot-check: PASSED** — test correctly detects the regression and clears after revert.

---

## C5 — check_rawdata_status signature (brief §3 C5)

Function at `src/web_console/backend/app.py` line 655:
```python
def check_rawdata_status(
    machine: str,
    mode: int,
    rawdata_root: Path | None = None,
    machines_config: Path | None = None,
) -> dict[str, Any]:
```

No `auto_delete_*` parameter present. Confirmed by `TestCheckRawdataStatusSignature::test_no_auto_delete_parameter_in_signature` (PASSES) and `test_accepted_parameters_are_read_only_in_intent` (PASSES — only `{machine, mode, rawdata_root, machines_config}` present).

The existing docstring at line 670 documents the historical removal: "Before 2026-04-21 this function took `auto_delete_mismatched=True` and unlinked md5-mismatched chunks directly — that was the M1|1 regression path."

**C5 check_rawdata_status signature: CLEAN**

---

## Subprocess vs in-process coverage

All 15 tests are in-process. This is appropriate because:
- C5 (signature introspection) — inherently in-process
- C2 (filter selection logic) — the `usable_entries` filter is in-process API layer, before any subprocess spawn
- C3 (read-only classification) — `_classify_chunks` and `check_rawdata_status` are in-process functions

Subprocess-mode coverage (analyzer consuming only matching-md5 chunks from disk) is provided by the existing `tests/backend/test_analyzer_e2e_md5_filter.py` which runs a real analyzer subprocess. That test passes (part of the 2213 passing tests in the full suite). The boundary is correctly defined in `03_tests.md`.

**Subprocess verified: N/A (in-process contracts; subprocess covered by pre-existing test_analyzer_e2e_md5_filter.py which passes)**

---

## Frontend changes

None. This ticket is docstring + test only. No frontend changes.

**Frontend preview verified: N/A**

---

## md5 / version invariants

No code changes to hash composition. The docstring explicitly documents that md5 is a tag, not a destruction signal. No cache write paths were modified.

**md5 round-trip check: N/A (docstring-only change)**

---

## Regressions in untouched areas

**Count: 0 new regressions**

The 1 pre-existing failure (`test_zero_win_but_fired_pid_retained_in_split`) is a missing-fixture issue on the M31 cache, pre-dating this ticket (test file unchanged, `git diff HEAD` confirms).

---

## Stop reasons

None. PASS verdict.
