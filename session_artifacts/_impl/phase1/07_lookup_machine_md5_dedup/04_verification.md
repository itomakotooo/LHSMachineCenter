# 04_verification.md — Ticket P1-B1: Consolidate _lookup_machine_md5 (real x 2)

**Verdict: PASS**

---

## Summary

All 6 brief section 3 contracts verified. All 39 new tests pass (were 37/39 at tester-time; the 2 intentionally-RED tests are now GREEN). Full backend suite: 2252 passed, 2 pre-existing failures identical to collab/dev baseline. No new regressions.

---

## C1 — Single source of truth

**Command:**

    python -c "from pathlib import Path; [...]"
    (see verification steps below)

**Observed:**

    Definitions found: 1
     - fresh_slotlab\machine_md5.py

**Verdict: PASS** — exactly 1 definition, in fresh_slotlab/machine_md5.py.

---

## C2 — Both callsites delegate

app.py (lines 548-601): _get_machine_md5 is a thin mode-aware wrapper retained for modesMd5 dispatch logic (brief section 3 C2 allows thin wrapper if signature must change). Its flat-schema fallback path delegates via lazy import of lookup_machine_md5 from fresh_slotlab.machine_md5 (line 573) and return lookup_machine_md5(machine, target) at line 601. No local body re-implementing the machines.json read logic. No local def _lookup_machine_md5 in app.py.

player_impact_analyzer.py (lines 59-84 and comment block at 2142-2146): The old def _lookup_machine_md5 body at old line 2138 is removed. The dual-path try/except import block at lines 59-84 includes the canonical import under the _lookup_machine_md5 alias for both package and standalone-script paths. The name _lookup_machine_md5 is preserved as a module-level attribute for monkeypatching — C5 parity test test_c5_save_chunk_cache_propagates_sentinel_via_module_attr confirms this works.

**Verdict: PASS** — both callsites delegate; no local body remaining.

---

## C3 — Value parity (config_md5 first, code_md5 second)

**Command (run directly):**

    python -m pytest tests/backend/test_lookup_machine_md5_canonical.py::TestC3ValueParity -v
    (15 tests, all PASSED)

Also verified manually:
- M14: ('4fcf00c48b3d6979aef058fed9ed5f94', '536fc5a2a8f2ecf1fd8c6dfcf2c025cc')
- M37: ('c226b1c302ec15647fd6584ae57078c5', '536fc5a2a8f2ecf1fd8c6dfcf2c025cc')
- M260: ('037fe950f73645bfcefeba86f3905a08', 'f9c245e3422703455facadbbbe4fbd31')

All match _EXPECTED_MD5 snapshots. Tuple order: config_md5 at index 0, code_md5 at index 1.

**Verdict: PASS**

---

## C4 — Virtual cousin documented, not merged

machine_md5.py module docstring explicitly names compute_machine_md5_for_mode, machine_version, and virtual — all three keywords checked by TestC4::test_canonical_docstring_references_virtual_cousin. The virtual function remains in machine_version.py (confirmed by AST test) and is absent from machine_md5.py.

**Verdict: PASS**

---

## C5 — P1-A2 parity test stays green

**Command:**

    python -m pytest tests/backend/test_summary_md5_writer_parity.py -v

**Observed:** 30 passed in 0.12s

Key monkeypatch chain test (test_c5_save_chunk_cache_propagates_sentinel_via_module_attr) PASSED — confirms _lookup_machine_md5 module-level alias in PIA propagates monkeypatched values to _save_chunk_cache call site.

**Verdict: PASS** — 30/30.

---

## New test suite

**Command:**

    python -m pytest tests/backend/test_lookup_machine_md5_canonical.py -v

**Observed:** 39 passed in 0.29s

Previously 37/39 at tester-time (2 intentionally RED). Both now GREEN after implementer completed the dedup.

**Verdict: PASS** — 39/39.

---

## Subprocess import smoke

**Command:**

    python -c "import fresh_slotlab.machine_md5; print('OK')"

**Observed:** OK (rc=0, no stderr, no unexpected stdout)

Also: TestImportSmoke::test_import_machine_md5_is_side_effect_free spawns a real subprocess and asserts rc=0 and empty stdout/stderr — PASSED.

**Verdict: PASS**

---

## Inject-bug verification (git stash method)

Steps executed:
1. git stash (stashed machine_md5.py + modified pia.py + modified app.py)
2. python -m pytest tests/backend/test_lookup_machine_md5_canonical.py -v

With stash applied (pre-dedup state), observed:

    FAILED tests/backend/test_lookup_machine_md5_canonical.py::TestC1SingleSourceOfTruth::test_exactly_one_def_lookup_machine_md5_in_repo
    FAILED tests/backend/test_lookup_machine_md5_canonical.py::TestC2CallersDelegateToCanonical::test_no_local_lookup_machine_md5_in_pia
    2 failed, 37 passed in 0.34s

C1 failure message: Expected exactly 1 definition of lookup_machine_md5, found 2 (machine_md5.py AND player_impact_analyzer.py old def)
C2 failure message: player_impact_analyzer.py still defines _lookup_machine_md5 locally

3. git stash pop
4. python -m pytest tests/backend/test_lookup_machine_md5_canonical.py -v
   Observed: 39 passed in 0.28s

**Verdict: PASS** — inject-bug correctly catches 2 structural violations; green after restore. Remaining 4 inject-bug scenarios are inline fixture-based tests in TestC6 (all GREEN).

---

## Full pytest regression

**Backend suite:**

    python -m pytest tests/backend/ -q
    2 failed, 2252 passed, 23 skipped, 2 xfailed, 5 warnings in 103.47s

Pre-existing failures (confirmed identical on collab/dev baseline via git stash):
1. tests/backend/test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split (missing rawdata/M31 fixture)
2. tests/backend/test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess (StubProcess thread timeout)

New regressions from this ticket: 0

**Integration and slot_designer suites:**

    python -m pytest tests/integration/ slot_designer/tests/ -q
    2 failed, 327 passed in 30.52s

Both failures (test_m37_mode5_analytic_includes_reroll_correction, test_pwdf_sensible_range) are pre-existing on collab/dev baseline (confirmed by git stash run: same 2 failures, 327 passed).

---

## Subprocess vs in-process coverage

| Check | Mode | Result |
|---|---|---|
| C1 structural (grep and AST) | In-process | PASS |
| C2 structural (no local def, import present) | In-process | PASS |
| C3 value parity (5 machines x 3 tests each) | In-process | PASS |
| C4 virtual cousin (AST and docstring) | In-process | PASS |
| C5 P1-A2 parity 30-test suite | In-process | PASS |
| C6 inject-bug TDD (4 fixture scenarios) | In-process monkeypatch | PASS |
| Import smoke (python -c subprocess) | Subprocess | PASS |
| Import smoke (pytest subprocess.run variant) | Subprocess | PASS |

---

## md5 / version invariants

The dedup does not change md5 algorithm, hash composition, or cache write paths. Canonical lookup_machine_md5 reads the same configSummaryMd5 / codeSummaryMd5 keys from the same configs/machines.json as the pre-dedup PIA implementation. Round-trip correctness verified by 15 snapshot tests in TestC3 and test_parity_with_pre_dedup_pia_implementation_m14. No md5 round-trip check required beyond value parity — this is a code-dedup ticket, not a hash algorithm change.

---

## Verdict: PASS

All brief section 3 contracts satisfied. Full backend suite clean (2 pre-existing only). No new regressions. Subprocess import verified safe. Inject-bug verified catches both structural contract violations.
