# Implementation Report — P1-A3: Frontend probe location documented

**Ticket**: `phase1/05_virtual_paytable_probe_docs`
**Verdict**: pass
**Date**: 2026-05-17

---

## Files changed

| File | Change | Lines | Brief section |
|------|--------|-------|---------------|
| `docs/PROD_VS_VIRTUAL_CONTRACT.md` | NEW — full asymmetry catalogue | 1–160 | §3 C1, C2 |
| `src/web_console/frontend/app.js` | 1-line cross-reference comment added | 4558 | §3 C3 |
| `slot_designer/core/backend/virtual_app.py` | 1-line cross-reference comment added | 159 | §3 C3 |

---

## Brief-section traceability

| Change | Brief section | Source artifact |
|--------|---------------|-----------------|
| Doc §A1: `/api/virtual/paytable/{m}` asymmetry | §3 C1, bullet 1 | `01_pipeline_map.md §4` "Where they diverge" row 3 (`_register_virtual_only_routes`); `01_pipeline_map.md §5 Q5` |
| Doc §A2: `_local_md5_refresh` asymmetry | §3 C1, bullet 2 | `01_pipeline_map.md §4` "Where they diverge" row 2 |
| Doc §A3: `_load_declared_pays_from_spec` asymmetry | §3 C1, bullet 3 | `01_pipeline_map.md §4` "Where they diverge" row 4 |
| Doc §A4: Two summary md5 patch sites | §3 C1, bullet 4 ("note P1-B2 consolidation") | `01_pipeline_map.md §4` "Where they overlap" row 2; `app.py:6945-6969`; `virtual_analyzer.py:500-558` |
| Doc §A5: Two inference trigger sites | §3 C1, bullet 5 ("note P1-B5 consolidation") | `01_pipeline_map.md §4` "Where they overlap" row 5; `app.py:85-194`; `virtual_analyzer.py:555-649` |
| Doc §B1: Frontend bundle single-sourced (positive) | §3 C1, bullet 6 | `01_pipeline_map.md §4` "Where they share" row 6 |
| Doc §B2: chunk_index + rawdata_index shared (positive) | §3 C1, bullet 7 | `01_pipeline_map.md §4` "Where they share" rows 4-5 |
| C2 fields (What/Why/Code location/Risk) on each entry | §3 C2 | all entries have all 4 fields |
| `app.js:4558` cross-reference comment | §3 C3 | probe site identified in §1 + `01_pipeline_map.md §5 Q5` |
| `virtual_app.py:159` cross-reference comment | §3 C3 | route registration site identified in §1 |

---

## Pytest results (touched modules)

- `virtual_app.py` is not directly test-targeted (docs-only; no functional change).
- `app.js` verified clean via `node --check src/web_console/frontend/app.js` (exit 0, no output).
- Full suite: **2262 passed, 33 skipped** (with 8 pre-existing failures deselected — all confirmed baseline failures before this ticket; see below).

### Pre-existing failures (baseline, not introduced by this ticket)

All confirmed by running `git stash && pytest <test> && git stash pop`:

| Test | Failure reason |
|------|---------------|
| `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` | Missing fixture file `rawdata/M31/mode_1/chunk_0001.json` |
| `test_chunk_index.py::TestSidecarRoundtrip::test_bulk_remove_entries_single_write` | Pre-existing (confirmed baseline) |
| `test_M15_verify_inject_bug.py::test_inject_pwdf_floor_breach` | Pre-existing (confirmed baseline) |
| `test_M15_verify_inject_bug.py::test_baseline_v2_iter0_pattern` | Pre-existing (confirmed baseline) |
| `test_M15_verify_inject_bug.py::test_inject_r1_blank_out_of_band` | Pre-existing (confirmed baseline) |
| `test_M15_verify_inject_bug.py::test_inject_bucket_rtp_out_of_band` | Pre-existing (confirmed baseline) |
| `test_M43_engine.py::test_chunk_schema_fingerprint_matches_production` | Missing fixture `rawdata/M43/mode_1/chunk_0001.json` |
| `test_M43_engine.py::test_chunk_envelope_keys_match_production` | Missing fixture `rawdata/M43/mode_1/chunk_0001.json` |

---

## Asymmetry coverage

| Entry | Intentional? | C2 fields complete? |
|-------|-------------|---------------------|
| A1 — `/api/virtual/paytable/{m}` | Yes | Yes |
| A2 — `_local_md5_refresh` | Yes | Yes |
| A3 — `_load_declared_pays_from_spec` | Yes | Yes |
| A4 — Two summary md5 patch sites | Accidental (P1-B2) | Yes |
| A5 — Two inference trigger sites | Accidental (P1-B5) | Yes |
| B1 — Frontend single-sourced | Non-asymmetry (positive) | Yes |
| B2 — chunk_index + rawdata_index shared | Non-asymmetry (positive) | Yes |

Total: 7 entries (5 asymmetries + 2 confirmed non-asymmetries). Brief requires
minimum 6 items across all bullet points in §3 C1 — **all 7 covered**.

---

## Cross-reference comments

| File | Line | Comment text |
|------|------|-------------|
| `src/web_console/frontend/app.js` | 4558 | `// Real ↔ virtual asymmetries catalogued in docs/PROD_VS_VIRTUAL_CONTRACT.md` |
| `slot_designer/core/backend/virtual_app.py` | 159 | `Full real ↔ virtual asymmetry catalogue: docs/PROD_VS_VIRTUAL_CONTRACT.md` |

Both comments are inline additions to existing comment blocks; no functional
code was touched.

---

## Open issues / out-of-scope items

1. **P1-B2 consolidation (A4)** — Two summary md5 patch sites documented as
   accidental duplication. Consolidation is out of scope for this docs-only
   ticket; tracked in P1-B2.

2. **P1-B5 consolidation (A5)** — Two inference trigger sites documented as
   accidental duplication. Tracked in P1-B5.

3. **Session-CI formula duplication** — `player_impact_analyzer.py:1012-1034`
   vs `virtual_analyzer.py:278-291`. Documented in `01_pipeline_map.md §4`
   "Where they overlap" row 3 but not included in the brief's minimum-6 list.
   Added as a candidate for a future asymmetry entry if arch team decides it
   warrants its own ticket. Intentionally not added to avoid scope creep beyond
   the 6 asymmetries the brief specifies.

4. **t-critical table duplication** — Same situation as #3. Deferred.

5. **Schema fingerprint duplication** — Same situation as #3. Deferred.

---

## Risk notes

- No runtime code change. This is docs + comments only.
- The `app.js` comment was added inside an existing comment block
  (lines 4472-4483). `node --check` confirmed clean parse.
- The `virtual_app.py` comment was added as a final line of an existing
  docstring. Python import still works (comment is inside a triple-quoted string).
- The pre-existing test failures are all fixture-file-missing or
  baseline-broken failures; none are related to this ticket's changes.
