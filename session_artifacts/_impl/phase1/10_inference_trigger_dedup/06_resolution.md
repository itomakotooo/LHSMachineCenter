# Ticket P1-B5 — Resolution

## Decision: **SHIP**

| Source | Verdict |
|---|---|
| impl-implementer | PASS (~13.1 min) — 3 files; backward-compat wrapper preserves OLD `_post_hook.json` format; 57/57 pytest |
| impl-tester | sufficient (~13.1 min) — 44 tests; 2/2 inject-bug; flagged timeout discrepancy (resolved by verifier as stale-state) |
| impl-verifier | PASS (~8.9 min) — all C verified; subprocess M14/virtual_analyzer e2e; baseline failures REDUCED 7→4 |
| impl-critic | APPROVE-WITH-REVISIONS — R1 silent OSError swallow / R2 dead constants / R3 vacuous test heuristic |

## Main session R1+R2+R3 fixes

**R1 — silent OSError swallow at `post_inference.py:448`**: critic correctly caught `_maybe_write_log` had `except OSError: pass` violating memory `feedback_no_silent_swallow.md`. Added stderr log before pass: `print(f"post_inference: could not write hook log to {log_path}: {type(exc).__name__}: {exc}", file=sys.stderr)` — matching the existing `_write_failure_diagnostic` pattern.

**R2 — dead constants at `app.py:81-82`**: removed `INFER_PAYTABLE_SCRIPT` + `VERIFY_LABELS_SCRIPT`. Wrapper uses `ROOT / "scripts"` directly. Comment block at the old location explains the removal for future readers.

**R3 — vacuous C2 test heuristic**: original test depended on `"INFER_PAYTABLE_SCRIPT" in text` which R2 removed → heuristic would become permanently False (vacuous). Rewrote `test_app_py_no_longer_has_inline_subprocess_inference_loop` to use regex extraction of the `_run_post_analyzer_inference` function body specifically and assert NO `subprocess.run` / `subprocess.Popen` / `subprocess.call` tokens inside.

## Post-fix verification

- 57/57 pytest pass (44 P1-B5 + 8 pre-existing logging + 5 batch-worker)
- R1 fix verified by reading the updated `_maybe_write_log`
- R2 dead-code removal verified by grep returning 0 hits
- R3 strengthened heuristic verified by running the test in isolation

## Architectural deferral (consolidated)

`_batch_gen_worker.py` is a 3rd callsite for post-inference scripts too (per implementer flag). Adds to the consolidated "bring worker to parity" follow-up that already includes P1-A4 R1 (md5 filter forwarding) and P1-B2 R1 (summary md5 patcher). Three known gaps in this one file:
1. P1-A4 R1: `--upstream-config-md5` / `--upstream-code-md5` CLI forwarding
2. P1-B2 R1: `patch_summary_md5(...)` call after analyzer returns
3. P1-B5 (this ticket): post-inference scripts trigger after analyzer

All three should be fixed together in a single follow-up ticket to rationalize `_batch_gen_worker.py`'s relationship with `_run_generate_report`.

## Pattern observed across Batch 1c (P1-B1 + P1-B2 + P1-B3 + P1-B5)

Every brief in Batch 1c assumed 2 callsites; reality consistently 3. The 3rd is `_batch_gen_worker.py` (B1/B2/B5) or `batch_dev_sampler.py` (B1) or `test_analyzer_resume.py` (B3). Future briefs should grep more thoroughly before claiming exact counts. Noted in PHASE_1_TICKETS.md.

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `fresh_slotlab/post_inference.py` NEW (canonical helper)
- `src/web_console/backend/app.py` MODIFIED (wrapper + R2 dead constants removed)
- `slot_designer/core/backend/virtual_analyzer.py` MODIFIED (delegation)
- `tests/backend/test_post_inference_canonical.py` NEW (44 tests; R3 strengthened heuristic)
- 6 markdown artifacts in `session_artifacts/_impl/phase1/10_inference_trigger_dedup/`
- `session_artifacts/_impl/phase1/PHASE_1_TICKETS.md` MODIFIED (add P1-B5 to consolidated worker follow-up)
