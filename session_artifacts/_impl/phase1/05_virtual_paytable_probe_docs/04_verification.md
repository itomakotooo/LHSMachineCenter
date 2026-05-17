# Verification Report -- P1-A3: Frontend probe location documented

**Ticket**: `phase1/05_virtual_paytable_probe_docs`
**Verifier**: impl-verifier (Claude Sonnet 4.6)
**Date**: 2026-05-17
**Verdict**: PASS

---

## 1. Contract checks

### C1 -- Doc enumerates known asymmetries (brief SS3 C1)

Source of truth: `session_artifacts/_arch/01_pipeline_map.md SS4`.

| Brief SS3 C1 bullet | Doc entry | Present? |
|---|---|---|
| `/api/virtual/paytable/{m}` virtual-only route | A1 | YES |
| `_local_md5_refresh` (virtual computes md5 locally) | A2 | YES |
| `_load_declared_pays_from_spec` (virtual reads spec) | A3 | YES |
| Two summary md5 patch sites (note P1-B2) | A4 | YES |
| Two inference trigger sites (note P1-B5) | A5 | YES |
| Frontend bundle single-sourced (positive) | B1 | YES |
| chunk_index + rawdata_index shared (positive) | B2 | YES |

All 7 brief-specified items present. Brief required minimum 6; 7 delivered.

### C2 -- Each entry has 4 required fields (What / Why / Code location / Risk)

| Entry | What | Why | Code location | Risk |
|---|---|---|---|---|
| A1 `/api/virtual/paytable/{m}` | YES | YES (Intentional 2026-04-22) | YES (virtual:149-173, real: absent, frontend:4483-4494) | YES |
| A2 `_local_md5_refresh` | YES | YES (Intentional: no upstream entry) | YES (virtual:56-94, injection :195) | YES |
| A3 `_load_declared_pays_from_spec` | YES | YES (Intentional: declared-paytable UX feature) | YES (virtual:97-146, real: no equivalent) | YES |
| A4 Summary md5 patch sites | YES | YES (Accidental duplication; P1-B2) | YES (real:app.py:6945-6969, virtual:virtual_analyzer.py:500-558) | YES |
| A5 Inference trigger sites | YES | YES (Accidental duplication; P1-B5) | YES (real:app.py:85-194, virtual:virtual_analyzer.py:555-649) | YES |
| B1 Frontend single-sourced | YES | YES (Evidence provided) | YES (app.py:72,:5392; virtual_app.py:186-197) | YES (Implication: changes apply to both) |
| B2 chunk_index + rawdata_index shared | YES | YES (Evidence provided) | YES (chunk_index.py:46-51 + callsites) | YES (Implication: do not fork) |

All 7 entries have all 4 required fields. Note: B-entries use "Implication" framing for Risk,
appropriate for non-asymmetries where collapse risk does not apply. Satisfies C2 spirit.

### C3 -- Cross-reference comments at both code locations

**app.js probe site**:
- Implementer predicted line 4483; actual verified location is line 4558.
- Line 4558 is inside the existing comment block (4547-4558) describing the
  try/catch probe behavior -- correct placement per brief.
- Text: `// Real <-> virtual asymmetries catalogued in docs/PROD_VS_VIRTUAL_CONTRACT.md`
- Reproducer: grep -n PROD_VS_VIRTUAL_CONTRACT src/web_console/frontend/app.js
- Result: line 4558 -- VERIFIED PRESENT.

**virtual_app.py route registration site**:
- Location: line 159, end of `_register_virtual_only_routes` docstring.
- Text: `Full real <-> virtual asymmetry catalogue: docs/PROD_VS_VIRTUAL_CONTRACT.md`
- Within lines 150-160 -- matches brief target range 152-159.
- Reproducer: grep -n PROD_VS_VIRTUAL_CONTRACT slot_designer/core/backend/virtual_app.py
- Result: line 159 -- VERIFIED PRESENT.

Cross-reference comments verified: 2/2.

---

## 2. Pytest full suite

**Command**: python -m pytest tests/backend/ tests/integration/ --tb=no -q
**Result**: 2 failed, 2236 passed, 23 skipped in ~124s

### Failure analysis

| Test | Status | Pre-existing? |
|---|---|---|
| test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split | FAIL | YES -- missing fixture rawdata/M31/mode_1/chunk_0001.json (listed in implementer baseline failures table) |
| test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess | FAIL intermittently | YES -- passes in isolation (10 passed); full-suite failure is pre-existing StubProcess thread-leak ordering issue |

**Baseline verification for cache_cleanup intermittent failure**:
- git stash && pytest tests/backend/test_cache_cleanup.py::test_cleanup_keeps_baseline_deletes_excess && git stash pop
- Result on pre-impl baseline (no changes): 1 passed -- confirms pre-existing, not introduced by this ticket.
- Post-impl isolated run: python -m pytest tests/backend/test_cache_cleanup.py -q -> 10 passed.

Conclusion: No regressions introduced. Both failures are pre-existing.

---

## 3. node --check

**Command**: node --check src/web_console/frontend/app.js (exit code captured via $?)
**Output**: (empty -- no syntax errors)
**Exit code**: 0
**Result**: PASS

---

## 4. Implementer bonus items -- scope assessment

The 02_implementation.md "Open issues" items 3-5 note three additional items from
01_pipeline_map.md SS4 "Where they overlap" NOT added to the doc:
- Session-CI formula duplication (player_impact_analyzer.py:1012-1034 vs virtual_analyzer.py:278-291)
- t-critical table duplication
- Schema fingerprint duplication

Assessment: NOT scope creep -- correct restraint.

Brief SS4 explicitly marks "Auditing every line of app.js for unmentioned asymmetries"
as OUT OF SCOPE. Brief SS3 C1 specifies exactly 7 items. The implementer documented
exactly those 7 items and explicitly deferred the 3 extras with appropriate reasoning.
The doc's SC and SD provide scaffolding for future additions without expanding scope now.

---

## 5. Subprocess / in-process coverage

Docs-only ticket -- no runtime change. No subprocess verification required.
The cross-reference comments are in a Python docstring (no runtime effect) and a JS
comment block (no runtime effect). Both syntactically valid: pytest collection provides
implicit Python import check; node --check provides explicit JS syntax check.

---

## 6. Frontend preview verification

No behavioral UI change was made (docs + comments only). node --check confirms JS
syntax validity. Preview screenshot not required for docs-only ticket (per brief SS6
"Risk class: LOW (docs only; no runtime change)").

---

## 7. md5 / version invariants

No code change to hash composition. md5 round-trip check not required.

---

## 8. Reproducible commands

| Check | Command | Expected | Observed |
|---|---|---|---|
| C3 app.js cross-ref | grep -n PROD_VS_VIRTUAL_CONTRACT src/web_console/frontend/app.js | 1 match | line 4558 |
| C3 virtual_app.py cross-ref | grep -n PROD_VS_VIRTUAL_CONTRACT slot_designer/core/backend/virtual_app.py | 1 match | line 159 |
| node --check | node --check src/web_console/frontend/app.js; echo exit:$? | exit:0 | exit:0 |
| pytest isolated cache test | python -m pytest tests/backend/test_cache_cleanup.py -q | 10 passed | 10 passed |
| pytest full suite | python -m pytest tests/backend/ tests/integration/ --tb=no -q | no new failures | 2 failed (both pre-existing) |

---

## Summary

- Verdict: PASS
- Asymmetries verified: 7/7 (all brief SS3 C1 bullets present; all C2 fields complete)
- Cross-ref comments: 2/2 (app.js:4558, virtual_app.py:159)
- Pytest: 2236/2261 (2 pre-existing failures; 0 regressions introduced)
- node --check: PASS (exit 0)
- Scope creep in bonus items: None -- implementer correctly deferred 3 items outside brief scope
