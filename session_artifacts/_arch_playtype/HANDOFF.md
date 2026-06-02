# HANDOFF — play-type re-architecture (READ THIS FIRST)

> As of 2026-06-02. Branch `claude/playtype-rearch`, HEAD `63dd609`. Companion to `DIRECTION.md`
> (the signed-off design/requirements — still valid). This doc = **AS-BUILT state + how to resume**.
> Where this disagrees with the design docs (`02_taxonomy.md` / `04_v2.md`), **THIS is current truth.**

## TL;DR
6 commits in. The architecture is **PROVEN** (first play-type carved byte-identical + proven-engaged).
All 12 pilots are **correctly analyzed** (byte-identical); **NO bugs remain** (even M274's old 4.87%
leak is already fixed). **1 of 15 play-types is carved** (the BCM cycle). All remaining work is
**purely structural ISOLATION** (carve the other play-types into base-excluded plugins for the
"改一台不连累全队" benefit) — real refactor value, **ZERO correctness urgency**.

## Committed + verified (branch `claude/playtype-rearch`)
| commit | what | gate |
|---|---|---|
| `6ab4f8a` | docs — design (DIRECTION + W1–W3 + 04_v2) | — |
| `7babf1e` | **A** framework: `play_types/` (MechanicAccumulator, PreParseProbe, ClaimSignature, PlayTypePlugin, detect_play_types, MachinePlayTypeConfig) + registry. Inert. | byte-identical (additive) |
| `ff5935c` | **B** wired into `parse_chunk_response`; flag `--use-play-type-plugins` (default **OFF**). Dormant. | byte-identical (9 pilots, flag on+off) |
| `adc42f6` | **C1** plumbing: per-ST ownership in the detector + 5 wiring fixes (topo order, type-aware merge, RoundCtx=rule-processed values, probe-before-detect, EC-4 diagnostic) | byte-identical + inject-bug |
| `6b10942` | **C2** BCMBasePlugin: **first real carve (MILESTONE)** — BCM cycle detection via shared helper `compute_robot_cycle_peaks` | byte-identical (5 BCM pilots) + inject-bug A (engaged) + B (logic) |
| `63dd609` | **C3** per-machine config layer: BCM `bonus_feature` migrated off the global `bcm_pairings.json` side-file into the **hashed** per-machine config; closed the silent-dependency | byte-identical + inject-bug |

Working tree clean. **Re-verified 2026-06-02 on HEAD `63dd609`:** the 4-file play-type run
(`test_play_type_framework` 82 + `_wiring` 38 + `_c1_fixes` 16 + `test_bcm_base` 34 = **170 passed, 0 failed**, 92s),
with `test_bcm_base` running LAST — the worst case for the cross-file `ALL_PLAY_TYPE_PLUGINS` pollution that the
autouse fixture guards against, so the inject-bug-A engagement tests are genuinely exercised under pollution pressure.
⚠ A **stale pre-fix** task-output (`tasks/bjn0ldqhs.output`, "2 failed, 168 passed") exists in the transcript dir —
**ignore it**; it predates the autouse-fixture fix and does NOT reproduce on current code.

## AS-BUILT deltas — corrections to the design docs (READ THESE)
1. **M274's 4.87% `_unattributed_st139` bug is ALREADY FIXED** (earlier work — BCMCycleAnchorRule, 2026-05-12).
   Verified: current M274 output has **no** fallback bucket. So the framing in `02_taxonomy.md` / `04_v2.md` /
   `DIRECTION §9` of it as "a bug PT-6 must fix" is **stale — there is no bug.**
2. **D/E/F (BCM reward variants: freespin / ListReward-minigame / lockreels) need NO separate plugins now.**
   The BCM reward is now a per-machine **config** (`bonus_feature`, C3); the variants are correctness-complete
   (byte-identical via BCMBase + config + the existing inline win-attribution). `04_v2 §9` Phase-1 #11–13
   (separate BCMFreespin/ListReward/LockReels plugins) → re-scoped to **hash-isolation only, DEFERRED**: it folds
   into the Phase-2 trigger-session/win-attribution carve (the freespin/minigame/etc. win attribution *is* that
   shared trigger logic).
3. **base_hash-VALUE pin tests are RE-PINNED, not deleted/xfail'd** (refines `DIRECTION §6`). Each transition
   commit that edits a closure file (parser.py etc.) legitimately moves `base_hash`; the pin tests
   (`test_analyzer_core_parser`/`_aggregator`, `test_wave_2c_universal_features`,
   `tests/analyzer/test_c3_5`/`c3`/`c5`/`c6`) are re-pinned to the new value **with a documented reason** =
   a conscious-acknowledgment gate. **STILL TODO (task #8):** the C-phase *output*-byte-identical tests
   (`test_c2_*`, `test_2b_*`) + canonical-md5 (`test_lookup_machine_md5_canonical`, `test_t_critical_table_canonical`)
   stay red — decide re-pin vs retire.
4. **Per-ST ownership** (the Commit-A detector gap) is implemented (C1): each observed ST is assigned to the plugin
   whose ClaimSignature signal fires in THAT ST's round-population (paid-field → paid ST; bonus-remark → bonus ST);
   same-ST conflicts resolve via the §4.6 precedence (structural-exclusion > dep-subordination > most-specific > tie-alert).

## Remaining work (re-scoped; structural isolation, NO correctness urgency)
- **LINCHPIN — Phase-2 trigger-session / win-attribution carve.** `trigger_sessions.py::compute_trigger_sessions`
  + the `round_win.py` rule classes are the heavy SHARED win-attribution logic that the BCM reward variants +
  scatter-freespin + TopDollar all use. Carving it (04_v2 §9 Phase-2: split into a Type-1 `RemarkTrigger` +
  Type-2 `WheelSelector`) unlocks isolation for that whole batch at once. Highest leverage.
- **Standalone play-type plugins** (some are clean C2-style carves): PT-7 wild-nudge (`is_wild_nudge_round`,
  self-contained), PT-1 pure-paid, PT-9/10/11 lock-symbol/lines/reels, PT-2 scatter, PT-8 TopDollar, PT-12 win-respin,
  PT-13 minigame, PT-14 multi-symbol-collection, PT-15 wheel-non-BCM.
- **Phase-3 fleet onboarding** — the other ~310 machines, the "add a new machine" way (auto-detect → per-machine
  config; ONBOARDING ALERT for genuinely-new mechanics). Do NOT batch all 420 at once.
- **Minor cleanup (non-blocking):** the `@pytest.mark.slow` marks (`test_bcm_base` 552/575/596, `test_play_type_wiring`
  281/299/323) are NOT registered — only `integration` is gated in `tests/conftest.py`. They emit "Unknown mark"
  warnings and currently don't deselect anything (the slow inject/subprocess tests run on every invocation). Either
  register+gate `slow` in conftest, or switch those tests to `@pytest.mark.integration`.

## How to resume — the proven recipe
1. **Carve pattern (C2 proved it; C2's FIRST attempt FAILED by reimplementing):** find the inline mechanic logic →
   **EXTRACT it into a shared pure helper in the base module** → have BOTH the inline (flag-off) path AND the
   plugin's accumulator call the SAME helper (identical by construction). **NEVER reimplement the logic inside the
   plugin** — that is exactly how C2's first attempt got the cycle rule wrong (used `cc<prev-1,prev>=5` instead of
   the inline `cc<prev,prev>10`).
2. **byte-identical gate:** run the analyzer **flag-OFF and flag-ON** vs the pristine goldens
   (`cache/_playtype_golden_pristine/<M>/player_impact_summary.json`, 9 pilots, captured at pristine HEAD; exact
   command + volatile-field list in `impl/golden_baseline.md`). Normalize OUT volatile fields (report_id, run_id,
   analyzer_version, effective_analyzer_version, timestamps) AND set-ordering (sort `top_symbols` /
   `payline_symbol_top20` / `paylines_top20`). **Read JSON as UTF-8** (default Windows gbk codec errors on these files).
3. **inject-bug per plugin (both):** (a) **engagement** — corrupt the plugin's output → the report changes → reverts
   clean (proves the plugin is genuinely wired, not bypassed by the carve gate); (b) **logic** — a synthetic fixture
   that distinguishes the correct rule from a plausible-wrong one.
4. **Test isolation (the exact pattern — replicate it):** `ALL_PLAY_TYPE_PLUGINS` is a module global. Every test
   FILE that relies on the registry MUST define a **module-level autouse fixture** that snapshots the registry at
   import time (AFTER the plugin self-registers) and resets to that snapshot before each test + restores after (see
   `test_bcm_base.py` lines 146–159 — `_REGISTRY_AT_IMPORT` + `_isolate_play_type_registry`). WITHOUT it, engagement
   tests are flaky: they pass alone, but a sibling FILE that mutates the registry first leaves BCMBase de-registered →
   the plugin never activates → the `99999 in cycle_peaks` engagement assertion fails (this is exactly what the stale
   "2 failed" artifact captured pre-fix). Per `memory/feedback_subprocess_import_suicide_and_module_globals.md`.
5. **⚠ AGENT-RELIABILITY:** in the prior session, **background impl agents died silently TWICE** (0-byte output,
   hours-stale, no completion notification — each cost hours of blind waiting). **Run agents FOREGROUND, or check
   liveness early** (file mtime/size + python processes); do NOT blind-wait on a background spawn. (Foreground W1–W3
   + the C2-fix succeeded; both silent deaths were background.)

## Process (unchanged — DIRECTION §7 + memory)
arch-* for design (done) · impl-* for build (implementer → tester → verifier → critic → committer). **Surgical commits**:
the working tree has pre-existing untracked/modified "junk" (`configs/machines.json`, `cache/`, `reports/`, prior
`session_artifacts/_impl`) — **NEVER `git add -A`; stage only your files by explicit path.** Adversarial review before
every commit (the prior session caught: a tautological fidelity test, a reimplemented cycle rule, a flaky engagement
test — all before they shipped).

## File map
- Framework: `fresh_slotlab/analyzer/play_types/{_base,_probe,_claim,_plugin,_machine_config,_detector}.py` + `fresh_slotlab/analyzer/play_type_registry.py`
- First plugin: `fresh_slotlab/analyzer/play_types/bcm_base.py` (self-registers; imported by `parser.py`)
- Shared cycle helper: `fresh_slotlab/round_classification.py::compute_robot_cycle_peaks`
- Parse-loop wiring + carve gate: `fresh_slotlab/analyzer/core/parser.py::parse_chunk_response` (flag `use_play_type_plugins`)
- Per-machine configs: `configs/play_type_configs/<M>/mode_<n>.json` (5 BCM pilots generated)
- Tests: `tests/backend/test_play_type_{framework,wiring,c1_fixes,c3_machine_config}.py` + `tests/backend/test_bcm_base.py`
- Goldens (ephemeral, NOT committed): `cache/_playtype_golden_pristine/` — command + volatile list in `impl/golden_baseline.md`
- Design record: `DIRECTION.md` (§1–11) + `01_pipeline_map` / `02_taxonomy` (the 15 play-types) / `03_coupling_audit` / `04_v2` / `05_critique` / `06_validation` + `impl/critique_commit{A,B,C1}.md`
