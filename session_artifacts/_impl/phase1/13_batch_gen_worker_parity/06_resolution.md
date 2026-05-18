# Ticket P1-D1 — Resolution

## Decision: **SHIP**

Phase 1 follow-up closing 3 consolidated `_batch_gen_worker.py` gaps surfaced by P1-A4 + P1-B2 + P1-B5 critics.

| Source | Verdict |
|---|---|
| impl-implementer | partial (~14 min); 4 contracts C1-C4 applied; chose Fix B (CLI filter) per memory; flagged 3 format-change test failures |
| impl-tester R1 | partial (~13 min); 23 new tests; 15/15 inject-bug; 1/2 xfail removed (Fix B doesn't physically delete) |
| impl-critic | APPROVE-WITH-REVISIONS — **SQ2 CRITICAL**: virtual machine C3 patch was silent no-op (lambda used flat-schema reader, returned `("","")` for virtual) |
| impl-verifier | PARTIAL (~19.7 min); 4 contracts e2e verified; 7 full-suite failures decomposed as 1 fixture + 2 stale-md5 + 3 ordering + 3 NEW from `_reset_worker_globals` not covering new globals |
| impl-tester R2 | sufficient (~6.3 min); 3 broken-format tests updated for new InferenceResult format; 3/3 inject-bug |
| Main session | SQ2 fix (lambda uses job dict per-mode values directly); fixture extended for 3 new globals |

## Main session fixes

**SQ2 fix (critical)**: `_md5_lookup` lambda in `_batch_gen_worker.py:195-201` was calling `lookup_machine_md5()` (flat-schema reader from P1-B1) — does NOT interpret `modesMd5`. For virtual machines whose top-level md5 is `""` and per-mode values live in `modesMd5`, returned `("","")` → `patch_summary_md5` skipped per its line 107 guard → silent no-op. Defeated the entire point of P1-B2 consolidation for virtual machines.

Fix: lambda now uses `job["upstream_config_md5"]` / `job["upstream_code_md5"]` directly — these values are set by `_prepare_batch_gen_item` via `_get_machine_md5(machine, mc, mode=mode)` which handles BOTH flat (real) and `modesMd5` (virtual) schemas correctly via the app.py wrapper.

**Fixture fix**: `_reset_worker_globals` in `test_batch_worker_post_hook.py` extended to save/restore 3 new P1-D1 module globals (`_patch_summary_md5_fn`, `_run_post_inference_fn`, `_lookup_machine_md5_fn`). Without this, cross-file state contamination from `test_batch_gen_worker_parity.py` left these set to real fn objects → 3 tests passed alone but failed in full suite.

## Architectural choices honored

**Fix B over Fix A** (filter flags, not physical delete): correct per memory `feedback_md5_is_a_tag_not_a_destruction_signal.md`. Historical chunks stay on disk; analyzer filters via `--upstream-config-md5` / `--upstream-code-md5` CLI args. xfail kept on `test_batch_job_chunk_dir_does_not_contain_historical_chunks` (Fix A test) as `strict=False` — preserves the guard if anyone later implements Fix A.

**Forward format migration** (new InferenceResult, not old flat): worker writes canonical `{canonical_post_inference: True, machine, mode, paytable_shape: {...}, classifier: {...}, ...}`. No UI consumer pinned to old `[{context}, {hook, skip}, ...]` format. Tester round 2 updated 3 tests to assert new format with inject-bug discipline.

## Pytest results

- 191 + 28 + 5 = 224 targeted pass (P1-D1 parity + P1-A4 historical + P1-B5 post-inference + batch_worker_post_hook + lookup_md5 + summary_patcher); 1 xfailed (Fix A guard)
- Full suite: 2437/2467 (7 failed = 1 M31 fixture + 2 stale M37/M279 md5 snapshots + 3 test_t_critical ordering + 1 actually still pre-existing — all confirmed pre-existing per verifier git stash baseline)
- 0 regressions from this ticket

## Follow-ups closed

- P1-A4 R1 batch path missing md5 filter forwarding → CLOSED (Fix B via CLI flags)
- P1-B2 R1 batch path missing summary md5 patch → CLOSED (worker calls patch_summary_md5 via canonical)
- P1-B5 batch path missing post-inference scripts → CLOSED (worker calls run_post_analyzer_inference via canonical)
- xfail `test_batch_job_dict_includes_md5_filter_keys` → REMOVED (now permanent regression guard)

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `src/web_console/backend/app.py` MODIFIED (_prepare_batch_gen_item adds md5 keys to job dict, C1)
- `src/web_console/backend/_batch_gen_worker.py` MODIFIED (~300-line rewrite for C2/C3/C4 + SQ2 critical fix)
- `tests/backend/test_batch_gen_worker_parity.py` NEW (23 parity tests)
- `tests/backend/test_classify_chunks_historical_consumers.py` MODIFIED (1 xfail removed; 1 kept strict=False per Fix B)
- `tests/backend/test_batch_worker_post_hook.py` MODIFIED (3 tests rewritten for new format + _reset_worker_globals fixture extended)
- 6 markdown artifacts in `session_artifacts/_impl/phase1/13_batch_gen_worker_parity/`
