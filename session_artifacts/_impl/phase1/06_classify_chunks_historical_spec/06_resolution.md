# Ticket P1-A4 — Resolution

> Main session consolidation of W1 + W2 rounds 1+2 + main-session R1/R3/R4 docstring fixes.

---

## Decision: **SHIP** (round 2 closed all blockers; round-2 critic APPROVE)

| Source | Round 1 | Round 2 |
|---|---|---|
| impl-implementer | pass (89-line docstring extension, 7 consumers) | R1+R3+R4 handled by main session inline |
| impl-tester | sufficient (15 tests, 1/1 inject-bug) | sufficient (+2 xfail batch-path tests, 17 total) |
| impl-verifier | PASS (2213/2238; 7 consumers confirmed) | PASS (15+2xfail; R1/R3/R4 verified) |
| impl-critic | APPROVE-WITH-REVISIONS (R1 batch path falsification / R2 missing batch inject-bug / R3 line numbers / R4 force-flag bypass) | **APPROVE** (3 ✓ / 1 ⚠ / 1 ✓-with-flag; no blockers) |

---

## Round 2 deltas

**R1 (main session) — Docstring honesty about batch path**:
Original docstring claimed `_prepare_batch_gen_item` "NEVER includes historical chunks". Critic round 1 found this false: Python-level `usable = kept + deletable` is bookkeeping only; raw `chunk_dir` is passed to `_batch_gen_worker.py` as `--from-cache` without md5 filter args. Updated docstring at `src/web_console/backend/app.py:997-1014` explicitly states this; xfail tests referenced as regression guard.

**R2 (impl-tester) — Batch-path xfail regression**:
Added `TestBatchPathHistoricalFilterGap` (2 tests, `strict=True`):
1. `test_batch_job_dict_includes_md5_filter_keys` — asserts job dict has `upstream_config_md5` + `upstream_code_md5` keys
2. `test_batch_job_chunk_dir_does_not_contain_historical_chunks` — asserts chunk_dir has zero historical-md5 chunks

Both fail today (real bug). `strict=True` means if a fix lands without removing xfail markers, pytest reports XPASS and fails the test — forces explicit removal.

**R3 (main session) — Line numbers**:
4 line references corrected. Per verifier: all now within `~tilde` approximation convention (max drift +/-54 lines on same function).

**R4 (main session) — Force-flag bypass**:
Added note to `delete_rawdata` consumer entry: when `force=True` the function takes `shutil.rmtree` path, `_classify_chunks` is NOT consulted.

---

## Pytest results

- Targeted: 15 pass + 2 xfailed in 0.57s
- Full suite: 2236 pass / 2 pre-existing failures (M31 fixture missing + cache_cleanup flaky) / 23 skipped / 2 xfailed
- 0 new regressions

---

## Real prod bug surfaced (no separate ticket yet — needs follow-up)

`_prepare_batch_gen_item` builds a job dict for `_batch_gen_worker.py` without `upstream_config_md5` / `upstream_code_md5` keys. Worker doesn't forward `--upstream-config-md5` / `--upstream-code-md5` as CLI args. Analyzer subprocess defaults to "no filter" and reads ALL `chunk_*.json` in the directory, including historical-md5 chunks.

**Impact**: batch-generate reports may unknowingly include historical chunks alongside current-md5 chunks, mixing two analytical contexts. Structurally demonstrable per critic SQ-R2-3; whether observed in prod is unconfirmed.

**Half-fix risk**: per critic SQ-R2-2 — a fix that adds keys to job dict BUT fails to forward them as CLI flags in `_batch_gen_worker.py` would pass both xfail tests (test 1: dict has keys ✓; test 2: chunk_dir still contains historical files ✓ because tests inspect dir, not subprocess argv). Fix PR must remove BOTH xfail markers together AND verify subprocess argv via existing `test_analyzer_e2e_md5_filter.py` pattern.

**Follow-up ticket needed**: see PHASE_1_TICKETS.md "Known follow-ups" section (added in this commit).

---

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `src/web_console/backend/app.py` MODIFIED (89-line round-1 docstring extension + main-session R1/R3/R4 updates)
- `tests/backend/test_classify_chunks_historical_consumers.py` NEW (17 tests: 15 pass + 2 xfail strict=True)
- 7 markdown artifacts in `session_artifacts/_impl/phase1/06_classify_chunks_historical_spec/` (00 ticket, 02 impl, 03 tests R1+R2 round 2, 04 verification rounds 1+2, 05 critique rounds 1+2, 06 resolution this doc)
- `session_artifacts/_impl/phase1/PHASE_1_TICKETS.md` MODIFIED (add Known Follow-ups section)
