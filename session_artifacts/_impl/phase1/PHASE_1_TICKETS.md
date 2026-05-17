# Phase 1 — Ticket Index

> Source: `session_artifacts/_arch/08_handoff.md §4 Phase 1`, `04_architecture_proposal_v5.md §6.1`, `01_pipeline_map.md §4 / §5`, `03_coupling_audit.md §4`.
>
> **Phase 1 goal**: dedup the 6 real ↔ virtual primitives + extract pure functions + migrate module globals to instance attributes + close 5 pre-Phase-1 documentation/spec blockers. Phase risk LOW-MEDIUM. Trivial rollback (revert per ticket).
>
> All tickets run through the impl-* 4-agent team (per `docs/IMPL_TEAM_PROCESS.md`). One ticket = one commit on `arch/console-refactor`.

---

## Execution order

Phase 1 ships in 4 batches. Within each batch tickets can run in parallel; across batches they're sequential (earlier batch establishes baseline that later batches build on).

| Batch | Tickets | Rationale |
|---|---|---|
| 1a — Baseline contracts | P1-A1, P1-A2 | Establish 3-invocation parity + 3-md5-writer parity tests BEFORE dedup work, so later dedups don't accidentally regress contracts |
| 1b — Bug fix + docs | P1-A5, P1-A3, P1-A4 | One real bug (compareReports race) + two doc tickets that don't touch code |
| 1c — Dedups | P1-B1, P1-B2, P1-B3, P1-B4, P1-B5 | The 5 dedup-only tickets; can run parallel after 1a establishes parity tests |
| 1d — Global migration | P1-B6, P1-C1 | Touches the most code (11 refs + broader pure-function extraction); done last to minimize chance of interleaved breakage |

Recommended **first ticket** (proof-of-concept for impl-* team): **P1-B4 t-critical table dedup** — smallest cross-cutting change, naturally exercises inject-bug TDD, no UI risk, ~1-2 hour cycle.

---

## Batch 1a — Baseline contracts (BLOCKING for 1c/1d)

### P1-A1 — 3-invocation-style parity test

**Citations**: `01_pipeline_map.md §5 question 1`, `08_handoff.md §4 Phase 1`.

**Problem**: analyzer is invoked three ways — (a) subprocess via `POST /api/runs` → `RunManager.start_run:4739` → `sys.executable <ANALYZER>`; (b) subprocess via `BatchRunManager:3160+` per-item; (c) in-process via `_run_generate_report:6700` (importing `pia` + monkey-patching `pia.post_json`, `sys.argv`, `os._exit`). All three should produce identical summary for the same input chunks. No spec or test asserts this.

**Deliverable**: `tests/integration/test_analyzer_three_invocation_parity.py` that, against a single cached chunk set (M14 mode 1 fixture), runs all three paths and `diff`s the produced summary.json. Each variant produces the same `summary.rtp.point_pct` + `player_impact.payout_ids_top20` + `code_md5` + `config_md5` to byte level (after stripping run_id / timestamps).

**Not in scope**: actually unifying the three paths (Phase 1 is just the contract test). Any drift surfaced → spawn follow-up ticket.

**Risk**: LOW (test-only). Rollback: delete the test file.

---

### P1-A2 — 3 summary md5 writers reconciled

**Citations**: `01_pipeline_map.md §5 question 3`, `03_coupling_audit.md §4.5 / §4.4`, `08_handoff.md §4 Phase 1`.

**Problem**: three writers fill `summary.code_md5` / `summary.config_md5` — (a) analyzer's own `_lookup_machine_md5:2163-2184` reads `configs/machines.json` inline; (b) backend `_run_generate_report:6955-6973` patches empty md5 post-`pia.main()`; (c) virtual `_patch_summary_md5_tags:506-558` patches post-delegate. No spec or test asserts all three agree.

**Deliverable**: `tests/backend/test_summary_md5_writer_parity.py` that simulates all 3 write paths on the same machine + mode, asserts identical `(code_md5, config_md5)` values land in the summary. Per memory `feedback_md5_granularity_and_stamping.md`: per-mode md5 path verified, virtual delegate path verified.

**Not in scope**: collapsing the three writers into one (that's part of Phase 1 dedup P1-B1 + P1-B2). This ticket only locks the parity contract.

**Risk**: LOW (test-only). Rollback: delete the test file.

---

## Batch 1b — Bug fix + documentation

### P1-A3 — Frontend probe location documented for `/api/virtual/paytable/{m}` 404 fallback

**Citations**: `01_pipeline_map.md §5 question 5`, `03_coupling_audit.md §4.5 last bullet`.

**Problem**: virtual-only endpoint `/api/virtual/paytable/{m}` is registered at `virtual_app.py:160-173`. Real console returns 404. Brief notes frontend probes + falls back gracefully. Cannot locate the specific catch around `apiGet:345`.

**Deliverable**: comment block at the actual probe site in `src/web_console/frontend/app.js` documenting the 404 fallback. Plus a note in `docs/ARCH_TEAM_PROCESS.md` (or a new `docs/PROD_VS_VIRTUAL_CONTRACT.md`) explaining the asymmetry.

**Not in scope**: making real console return the same endpoint with a stub. Asymmetry is intentional per virtual_app.py:152-159 contract.

**Risk**: LOW (docs only). Rollback: revert comment + doc.

---

### P1-A4 — `_classify_chunks` historical semantics spec'd

**Citations**: `01_pipeline_map.md §5 question 7`, memory `feedback_md5_is_a_tag_not_a_destruction_signal.md`, memory `feedback_enumerate_safety_paths.md`.

**Problem**: `_classify_chunks:889-1039` returns three lists (kept / deletable / historical). Per docstring (`896-922`) this is "**not** a deletion decision — it's a tag for display + analyzer filtering". But the historical bucket IS consumed by `_run_generate_report:6733` to decide which chunks the in-process replay sees. Cannot verify from observation whether historical chunks ever feed an analyzer run unintentionally.

**Deliverable**:
1. Docstring update at `_classify_chunks` listing all known consumers + their semantics (display / filter / read-but-not-replay)
2. `tests/backend/test_classify_chunks_historical_consumers.py` asserting that historical-bucket chunks are NEVER passed to analyzer execution paths (per the memory's "tag, not destruction signal" invariant)
3. Per memory `feedback_md5_is_a_tag_not_a_destruction_signal.md`: confirm no path silently relies on `historical` to mean "auto-deletable"

**Not in scope**: renaming `historical` (per the memory, rename to `historical` from `stale` was deferred). Rename is a separate ticket if needed.

**Risk**: LOW (docs + test). Rollback: revert.

---

### P1-A5 — `compareReports` cache-bust race fix

**Citations**: `01_pipeline_map.md §5 question 8`.

**Problem**: frontend `compareReports:3477` and `_enterCompareMode:3505` fetch two report summaries by version; `metaA.mode` `3491` comes from `compareSelected` Map `9-147`. Frontend assumes reports stay byte-identical for `(machine, mode, version)`, but `DELETE /api/reports/.../{version}` `7735` can rmtree the directory mid-compare. No cache-bust on selection clear; transient 404s + stale frontend state during a delete+compare race.

**Deliverable**:
1. Identify the race in `app.js` (read `compareReports`, `_enterCompareMode`, `compareSelected` Map cleanup, DELETE handler)
2. Per memory `feedback_error_branch_resets_all_state.md`: any DELETE path must clear `compareSelected` entries for the deleted (machine, mode, version) AND reset compare UI panels
3. Per memory `feedback_fasttimer_overlap_needs_oneshot.md`: if compare uses polling, add one-shot guard
4. Regression test: `tests/frontend/test_compare_reports_cache_bust.py` (or `.js` test if a test harness exists) — fakes DELETE during compare, asserts UI doesn't show stale data
5. Preview-verify per memory `feedback_frontend_verify_before_commit.md`

**Not in scope**: refactoring the DELETE flow itself.

**Risk**: MEDIUM (frontend UI change). Rollback: revert the cache-bust commit.

---

## Batch 1c — Dedups

### P1-B1 — Consolidate `_lookup_machine_md5` (real × 2)

**Citations**: `01_pipeline_map.md §4 row 1 "md5 computation for chunk stamping"`, `03_coupling_audit.md §4.5`.

**Problem**: `_lookup_machine_md5` defined in both `src/web_console/backend/app.py:548-591` and `fresh_slotlab/player_impact_analyzer.py:2163-2184`. Both read `configs/machines.json`. Two implementations; should be one shared helper.

**Deliverable**:
1. Move canonical impl to `fresh_slotlab/machine_md5.py` (new file) or extend `slot_designer/core/backend/machine_version.py`
2. Replace both callsites to import from canonical location
3. Per memory `feedback_no_parallel_panel_impl.md`: identify if virtual `compute_machine_md5_for_mode` should also use the same primitive; document the relationship
4. Regression test proves dedup: revert dedup → inject divergent value in one impl → assert test catches the divergence

**Not in scope**: changing md5 algorithm or composition rules (per `04_v5 §4 hash composition unchanged`).

**Risk**: LOW-MEDIUM. Rollback: revert.

---

### P1-B2 — Consolidate summary md5 patcher (real × 2)

**Citations**: `01_pipeline_map.md §4 row 2 "md5 patch into summary"`, `03_coupling_audit.md §4.5`.

**Problem**: `_run_generate_report:6955-6973` (real) and `_patch_summary_md5_tags:506-558` (virtual) both patch empty md5 fields into summary post-analyzer. Same intent. Two impls. Per memory `feedback_md5_granularity_and_stamping.md`: both paths must be patched together when md5 schema changes — easy to miss one.

**Deliverable**:
1. Extract shared helper `patch_summary_md5(summary_path, md5_lookup_fn)` in `fresh_slotlab/summary_md5_patch.py` (new file)
2. Real callsite + virtual callsite both call the shared helper
3. Helper accepts an injectable `md5_lookup_fn` (defaults to real lookup; virtual injects local lookup)
4. Regression: inject divergent patch → test catches

**Depends on**: P1-A2 (parity test must be in place to catch regressions)

**Risk**: LOW-MEDIUM. Rollback: revert.

---

### P1-B3 — Consolidate session-CI half-width (real × 2)

**Citations**: `01_pipeline_map.md §4 row 3 "session CI half-width"`, `03_coupling_audit.md §4.5`.

**Problem**: `session_halfwidth_pp` in `player_impact_analyzer.py:1012-1034` + `_ci_halfwidth_pp` in `virtual_analyzer.py:278-291`. Same formula; comment at virtual_analyzer.py:282-283 says "matches the formula used by the real analyzer". Two impls; one canonical.

**Deliverable**:
1. Move canonical formula to `fresh_slotlab/sampler.py` (where `compute_ci_halfwidth_pp` already lives — per `03 §4.5`)
2. Real analyzer imports from sampler; virtual analyzer imports from sampler
3. Regression: inject divergence → test catches

**Risk**: LOW. Rollback: revert.

---

### P1-B4 — Consolidate t-critical table (real × 2) — RECOMMENDED FIRST TICKET

**Full brief**: `session_artifacts/_impl/phase1/01_t_critical_table_dedup/00_ticket.md`

**Citations**: `01_pipeline_map.md §4 row 4 "t-critical table"`, `03_coupling_audit.md §4.5`.

**Problem**: `t_critical_95` in `player_impact_analyzer.py:965-997` + `_T_CRITICAL_95_TABLE + _t_critical_95` in `virtual_analyzer.py:262-275`. Two t-critical tables; virtual's is smaller (sentinel 1.96 for df>30 vs analyzer's piecewise interp). Latent divergence.

**Risk**: LOW. Rollback: revert.

---

### P1-B5 — Consolidate inference-trigger (real × 2)

**Citations**: `01_pipeline_map.md §4 row 5 "inference scripts trigger"`, `03_coupling_audit.md §4.5`, `01_pipeline_map.md §5 question 2`.

**Problem**: `_run_post_analyzer_inference` in `app.py:85-194` + `_run_inference_scripts` in `virtual_analyzer.py:561-649`. Same `paytable_shape` + `classifier` subprocess calls. Different argument signatures. Diverging error reporting. Per memory `feedback_no_silent_swallow.md`: best-effort post-hooks must persist diagnostic to disk.

**Deliverable**:
1. Extract shared helper `run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts)` in `fresh_slotlab/post_inference.py` (new file)
2. Both real + virtual callsites call shared helper
3. Per memory `feedback_no_silent_swallow.md`: helper writes failure diagnostic (rc + stderr tail) to disk; never silent
4. Regression: inject failure → test asserts diagnostic landed on disk

**Risk**: MEDIUM (subprocess paths; per memory `feedback_perf_claim_needs_e2e_event_stream.md` need subprocess-mode verification). Rollback: revert.

---

## Batch 1d — Global migration

### P1-B6 — `RAWDATA_ROOT` global → `BatchRunManager` instance attribute (11 refs)

**Citations**: `03_coupling_audit.md §4.1`, `08_handoff.md §4 Phase 1`, memory `feedback_subprocess_import_suicide_and_module_globals.md`.

**Problem**: `RAWDATA_ROOT` declared at `app.py:518`. Code comment at `app.py:3769` already flags it: "Use the BatchRunManager's injected rawdata_root, not the module-level RAWDATA_ROOT global. Virtual console vs real console have different roots; hardcoding the global here made every virtual batch-run target the REAL console's rawdata/ tree." 11 references remain in app.py.

**Deliverable**:
1. Audit all 11 refs (`grep RAWDATA_ROOT src/web_console/backend/app.py`)
2. For each: replace with `self._rawdata_root` where the call is inside `BatchRunManager` / `RunManager` / per-request handler that has access to injected root
3. For top-level callers without a request context, take `rawdata_root` as a parameter (don't fall back to module global)
4. Per memory `feedback_subprocess_import_suicide_and_module_globals.md`: split-path regression test that monkeypatches the module global to a wrong value and asserts BatchRunManager / virtual paths still use the injected root, not the global
5. Per memory `feedback_enumerate_safety_paths.md`: every path documented; inject-bug verified per ref

**Risk**: MEDIUM (touches multiple call paths; subprocess-mode verification mandatory). Rollback: revert.

---

### P1-C1 — Pure-function extraction + remaining module-global migration

**Citations**: `08_handoff.md §4 Phase 1`, `03_coupling_audit.md §4.1`.

**Problem**: beyond `RAWDATA_ROOT`, several other module globals in `app.py` are footguns (`_MACHINES_SUMMARY_CACHE`, `_RAWDATA_OVERVIEW_CACHE`, `_STATIC_ATTRS_CACHE`, `_IN_USE_MODES`, `_LOCK_CACHE` per `03 §4.1`). Also pure functions in app.py / player_impact_analyzer.py that should be extractable to side-effect-free modules.

**Deliverable**: per-target sub-tasks within this ticket (each one inject-bug TDD verified):
1. `_MACHINES_SUMMARY_CACHE` → per-instance cache or per-request memo
2. Same for `_RAWDATA_OVERVIEW_CACHE`, `_STATIC_ATTRS_CACHE`, `_IN_USE_MODES`, `_LOCK_CACHE`
3. Extract truly-pure functions (e.g., bucket classifiers, schema validators) to standalone modules

**Risk**: MEDIUM-HIGH (broad surface). Rollback per sub-task: revert.

**Note**: this ticket can be sub-divided further at implementation time. If main session finds the scope too large for one impl-* cycle, split into P1-C1a / P1-C1b / etc.

---

## Status tracker (filled in as tickets complete)

| Ticket | Status | Branch commit | impl-critic verdict |
|---|---|---|---|
| P1-A1 | NOT STARTED | — | — |
| P1-A2 | NOT STARTED | — | — |
| P1-A3 | NOT STARTED | — | — |
| P1-A4 | NOT STARTED | — | — |
| P1-A5 | NOT STARTED | — | — |
| P1-B1 | NOT STARTED | — | — |
| P1-B2 | NOT STARTED | — | — |
| P1-B3 | NOT STARTED | — | — |
| **P1-B4** (FIRST) | **READY** (`00_ticket.md` written) | — | — |
| P1-B5 | NOT STARTED | — | — |
| P1-B6 | NOT STARTED | — | — |
| P1-C1 | NOT STARTED | — | — |

---

## Next action

After Claude Code restart (required to hot-load `.claude/agents/impl-*.md`):

1. **Smoke-test the 4 impl-* agents** per `docs/IMPL_TEAM_PROCESS.md §9`. Expected: 6-15 sec each. If any fail "Agent type not found" → another restart.
2. **Run ticket P1-B4** through the impl-* team flow:
   - Spawn `impl-implementer` + `impl-tester` in parallel (Wave 1) with `session_artifacts/_impl/phase1/01_t_critical_table_dedup/00_ticket.md` as brief
   - Wait for both notifications
   - Spawn `impl-verifier` + `impl-critic` in parallel (Wave 2) with full chain (W1 outputs)
   - Wait for both notifications
   - Main session reads `04_verification.md` + `05_critique.md` → writes `06_resolution.md` → commits with critic's `## Self-critique` section
3. **Then proceed to Batch 1a** (P1-A1 + P1-A2 in parallel) before any further dedup tickets.
