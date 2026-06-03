# impl-critic: Phase D (DELETE play-type plugin framework) — critique

**Date:** 2026-06-03  
**Branch:** `claude/playtype-rearch`  
**Base:** HEAD = `88d212e` (all Phase D changes are uncommitted working tree)  
**Verdict:** APPROVE-WITH-FIXES (1 MINOR required before commit)

---

## Top concerns

1. One dangling docstring ref in a non-closure file survived the coordinator's fix pass (`bcm_cycle.py:112` still says `BCMBaseAccumulator.on_robot_end` — a deleted class). Non-closure → does not affect `base_hash`; does not break anything at runtime. MINOR, but the brief explicitly demanded no dangling refs, and the coordinator claimed "3 stale refs fixed" without catching this one.

2. The byte-identical evidence in `cache/_phaseD_tester_*` covers all 7 machines (M14, M15, all 5 BCM pilots) for mode 1 only. M268/M272/M275/M279 each have modes 2/5/7 in `rawdata/`. The brief required "across the modes present in cache". For non-mode-1, the L0 path was already inert (no `play_type_configs/M*/mode_2.json` etc. existed), so the byte-identical argument is even stronger there — but the evidence was not captured. This is a coverage gap in the tester's execution, not a functional risk.

3. The docstring in `test_bcm_cycle_carve.py:44` references `test_bcm_cycle_tester_byte_identical_gate_all_machines` as if it is a test function in the suite; this function does not exist. The byte-identical check lives in `cache/_phaseD_tester_*` artifacts (committed to disk but not in `tests/`). This is a documentation inaccuracy.

---

## Stress questions (10+)

**Q1** (MINOR — required fix). `fresh_slotlab/analyzer/play_types/bcm_cycle.py:112`: the function docstring for `compute_robot_cycle_peaks` says "Both the inline parser.py accumulation and `BCMBaseAccumulator.on_robot_end` call this function." `BCMBaseAccumulator` is a deleted class. The brief says "grep -rn 'play_type' fresh_slotlab/ returns ONLY the 2 carve files (no dangling framework references)" — this line violates that. The coordinator fixed the module docstring (line 9) and the `test_bcm_base.py` reference (line 137) but missed this third occurrence at line 112. **Status: present, unfixed.**

**Q2** (PASS). The two `if not _bcm_base_active:` guards in the old parser.py (at old:2441 guarding `chunk_collect_seen += 1`, and at old:2468 guarding `chunk_cycle_peaks.extend(robot_cycle_peaks)`) were the flag-ON bypass paths. In Phase D, `chunk_collect_seen += 1` is now inside `if robot_collect_observed:` unconditionally (parser.py:2100), and `if robot_cycle_peaks: chunk_cycle_peaks.extend(...)` is unconditional (parser.py:2113-2114). The flag-off path is the now-unconditional path. Verified by direct diff between HEAD and working tree at those exact lines. The computation is identical.

**Q3** (PASS). Is the byte-identical claim evidenced or hand-waved? The `cache/_phaseD_tester_pre/` + `cache/_phaseD_tester_post/` directories contain both pre- and post-change reports for M14, M15, M268, M272, M274, M275, M279 (all mode 1). Independent verification of M279 and M14/M15: after normalizing volatile fields (`report_id`, `run_id`, `analyzer_version`, `effective_analyzer_version`, `generated_at`, `elapsed_seconds`, `evaluated_at`, `run_timestamp`, `sampling`), all 7 machines are byte-identical. For M279 (the critical medium-confidence pilot), `collect_mechanic.feature_match.bonus_feature_source` = `"config"` in both pre and post — the L0→L1 transition held `source="config"`. Evidence is real, not hand-waved.

**Q4** (PASS, with coverage note). The 5 BCM pilots were each tested on mode 1 only. Modes 2/5/7 exist in rawdata for M268/M272/M275/M279. However, `configs/play_type_configs/` only ever had `mode_1.json` files — modes 2/5/7 had no L0 entry even before Phase D (`_machine_config.py` would have returned `None` for those modes → L0 was already inert). The byte-identical argument for those modes is trivially stronger, but the evidence was not captured. This matches the brief's requirement "5 BCM pilots across the modes present in cache" — PARTIALLY violated. Not a functional risk but a process gap.

**Q5** (PASS). Are the 13 salvaged `TestComputeRobotCyclePeaks` tests in `test_bcm_cycle_carve.py` genuine or tautological? The two discriminating tests are verified genuine: `test_small_peak_not_recorded` (cc=1..8 → reset, asserts `peaks==[]`; old buggy rule WOULD record `[8]` since `8>=5` → would fail) and `test_single_step_drop_recorded` (cc=50→49 single-step drop; old rule `49<49` is False → would miss it → test `assert 50 in peaks` would fail). The inject-bug recipe precisely describes the flip behavior for each. Not tautological.

**Q6** (PASS). Coverage of `detect_cycle_peak`, `at_cycle_peak_indices`, `infer_bcm_target_spin_type`: the tester's claim that these have coverage in `test_round_classification.py` is confirmed. `test_round_classification.py` imports all three directly from `fresh_slotlab.analyzer.play_types.bcm_cycle`. Their only prior coverage was in these round_classification tests (not the deleted `test_bcm_base.py`). The deletion of `test_bcm_base.py` did not lose unique coverage for these functions.

**Q7** (PASS). Dead framework symbols in production code after Phase D: grep over `fresh_slotlab/` for all framework symbols (`use_play_type_plugins`, `play_type_registry`, `MachinePlayTypeConfig`, `detect_play_types`, `BCMBasePlugin`, `BCMBaseAccumulator`, `_active_plugins`, `_chunk_plugin_partial`, `_robot_accs`, `_pt_config`, `RoundCtx`, `MechanicAccumulator`) returns ZERO hits except the single `bcm_cycle.py:112` function-docstring reference. The `play_type_config=` kwarg is gone from both `_resolve_bonus_feature` call sites in PIA. The `--use-play-type-plugins` arg is gone from `base_pipeline.py`. No orphaned imports, dead variables, or unreachable branches survive.

**Q8** (PASS). `feedback_subprocess_import_suicide_and_module_globals.md`: the deleted `bcm_base.py` self-registered via `_register(BCMBasePlugin())` at module import. Both the registrant (`bcm_base.py`) and the registry (`play_type_registry.py`) are deleted. No remaining code calls `get_all_plugins()`. The `play_types/__init__.py` no longer imports any of the framework modules. Zero import-time side-effects remain. No surviving code relied on the registration.

**Q9** (PASS). `feedback_invariant_with_fallback_hides_drift.md`: removing C3 L0 only changes which layer provides `bonus_feature`/`bonus_feature_source`. The `_unattributed_st<N>` fallback synthesizer in `parser.py:1893` is untouched. `_resolve_bonus_feature` now goes directly to L1 (bcm_pairings) → `source="config"` for the 5 pilots. For non-pilot machines, L0 was already `None` so L1 was already the effective layer. No new silent fallback was introduced.

**Q10** (PASS). base_hash re-pin completeness: all 8 required pin tests updated from `85666c4c4407` → `8a791a69cd05` with documented reason. `test_analyzer_core_parser.py:757`, `test_analyzer_core_aggregator.py:1307`, `test_wave_2c_universal_features.py:740`, `test_c3_5_isolation_m275_only.py:113`, `test_c3_base_hash_flips_for_round_level_enrichment.py:90`, `test_c5_byte_identical_unrelated_fields.py:117`, `test_c6_byte_identical_bonus_chain.py:128`, `test_c6_carve_completion.py:132` — all confirmed. The remaining `85666c4c4407` occurrence at `test_analyzer_core_parser.py:769` is in a history-trail comment inside the assert error message, not an assertion itself. Acceptable.

**Q11** (PASS). Commit hygiene — surgical staging. The working tree contains 618 pre-existing unstaged `slot_designer/` deletions, modified `configs/machines.json`, modified `session_artifacts/` docs, and `cache/` / `reports/` junk. None of these must be staged. The Phase D files are all in `fresh_slotlab/`, `tests/`, and `configs/play_type_configs/`. A `git add -A` or `git add .` here would corrupt the commit with unrelated changes.

**Q12** (PASS). `test_bcm_cycle_carve.py:44` references a non-existent test function `test_bcm_cycle_tester_byte_identical_gate_all_machines`. This is a documentation inaccuracy only — the byte-identical evidence lives in `cache/_phaseD_tester_*` artifacts and was confirmed manually. No test in `tests/` is missing; the docstring claim is misleading but not functional.

**Q13** (PASS). Concurrency / production failure thought experiment: 10 concurrent planners all hammering `parse_chunk_response` post-Phase-D. The function is pure computation (no shared state, no module globals mutated). The removed `_bcm_base_active` flag was a local variable computed at the start of each `parse_chunk_response` call — its removal cannot introduce race conditions. The `compute_robot_cycle_peaks(rounds)` call is a pure function with no shared state. No new concurrent risk.

**Q14** (PASS). The `--use-play-type-plugins` argument was `action="store_true", default=False`. After Phase D, the argument no longer exists. The verifier confirmed `--use-play-type-plugins` is absent from `--help`. No production CLI invocation set this flag (confirmed: no scripts, configs, or web-console code passed it). Its removal cannot break any real invocation.

---

## Memory-feedback violations

**Count: 0 violations.**

- `feedback_enumerate_safety_paths.md`: inject-bug B recipe documented + proven for 2 discriminating tests. HONORED.
- `feedback_subprocess_import_suicide_and_module_globals.md`: no import-time side effects introduced; bcm_base self-registration dependency eliminated. HONORED.
- `feedback_invariant_with_fallback_hides_drift.md`: `_unattributed` fallback synthesizer untouched. HONORED.
- `feedback_no_silent_swallow.md`: no new `except: pass` introduced. HONORED.
- `feedback_perf_claim_needs_e2e_event_stream.md`: tester ran real subprocess against cached M15/M279 chunks. HONORED.

---

## Code-level bugs / risks

- None found that affect runtime behavior.
- The `BCMBaseAccumulator.on_robot_end` stale docstring reference at `bcm_cycle.py:112` is the only remaining artifact of the deleted framework. It is in a docstring of a non-closure file — zero runtime impact, zero base_hash impact. It is factually incorrect (the function now has only one caller: parser.py's inline accumulation).

---

## Test-level gaps

- `test_bcm_cycle_tester_byte_identical_gate_all_machines` referenced in `test_bcm_cycle_carve.py:44` docstring does not exist as a test function. Misleading documentation.
- Mode 2/5/7 byte-identical not captured in `cache/_phaseD_tester_*` for M268/M272/M275/M279. Not a functional gap (L0 was inert for those modes), but brief §6.1 asked for "modes present in cache".

---

## Claim-vs-reality gaps (commit message vs diff)

**Commit message:** "Gates: byte-identical 7 machines; 2 inject-bugs; zero suite regressions (worktree delta); e2e M275/M15 clean."

Reality:
- "byte-identical 7 machines": TRUE for mode 1 on all 7. FALSE for modes 2/5/7 (not run). Claim is technically accurate but incomplete.
- "2 inject-bugs": TRUE (inject-bug A = closure edit → base_hash flip; inject-bug B = old rule → 2 discriminating tests RED). VERIFIED.
- "zero suite regressions": TRUE per verifier's worktree delta analysis (132 failures all pre-existing). VERIFIED.
- "e2e M275/M15 clean": TRUE (M275 and M15 in tester artifacts show IDENTICAL pre/post; `bcm_bonus_source="config"` for M275). VERIFIED.
- "8 pins re-pinned": TRUE. VERIFIED.
- "base_hash 85666c4c4407→8a791a69cd05": TRUE. VERIFIED.
- "Kept the 2 function carves": TRUE. bcm_cycle.py and wild_nudge.py are untouched in logic. VERIFIED.

---

## Edge cases not covered

- Modes 2/5/7 byte-identical (no L0 config ever existed for them → trivially safe, but not evidence-captured).
- The `_unattributed_residual` synthesizer behavior when `_resolve_bonus_feature` returns `(None, "none")` for a new BCM machine (no entry in `bcm_pairings.json`) — this was already the behavior before Phase D (L0 was only populated for the 5 pilots; all other machines went to L2 heuristic or L3 none). Phase D does not change this.

---

## Required fixes before commit/merge

1. **[MINOR — REQUIRED]** Fix `fresh_slotlab/analyzer/play_types/bcm_cycle.py:112`. Change:
   > Both the inline parser.py accumulation and `BCMBaseAccumulator.on_robot_end` call this function.
   
   To:
   > The inline parser.py accumulation calls this function as the single source of truth for per-robot cycle-peak lists.

   Reason: `BCMBaseAccumulator` was deleted in Phase D. The brief's import-smoke gate requires `grep -rn "play_type" fresh_slotlab/ src/` returns only the 2 carve files with no dangling framework references. This line references a deleted class. The fix is docstring-only and does NOT affect `base_hash` (bcm_cycle.py is not in `_CLOSURE_FILES`).

---

## Optional improvements

1. Capture modes 2/5/7 byte-identical evidence in `cache/_phaseD_tester_*` for M268/M272/M275/M279 (belt-and-suspenders, brief §6.1 technically asked for it).
2. Remove or correct the `test_bcm_cycle_tester_byte_identical_gate_all_machines` docstring reference in `test_bcm_cycle_carve.py:44` to avoid confusion about what is and is not a committed test.

---

## Exact surgical `git add` path list

Stage ONLY these paths. Do NOT use `git add .` or `git add -A`.

```
# Deletions (framework code)
git rm configs/play_type_configs/M268/mode_1.json
git rm configs/play_type_configs/M272/mode_1.json
git rm configs/play_type_configs/M274/mode_1.json
git rm configs/play_type_configs/M275/mode_1.json
git rm configs/play_type_configs/M279/mode_1.json
git rm fresh_slotlab/analyzer/play_type_registry.py
git rm fresh_slotlab/analyzer/play_types/_base.py
git rm fresh_slotlab/analyzer/play_types/_claim.py
git rm fresh_slotlab/analyzer/play_types/_detector.py
git rm fresh_slotlab/analyzer/play_types/_machine_config.py
git rm fresh_slotlab/analyzer/play_types/_plugin.py
git rm fresh_slotlab/analyzer/play_types/_probe.py
git rm fresh_slotlab/analyzer/play_types/bcm_base.py

# Deletions (framework tests)
git rm tests/backend/test_bcm_base.py
git rm tests/backend/test_play_type_c1_fixes.py
git rm tests/backend/test_play_type_c3_machine_config.py
git rm tests/backend/test_play_type_framework.py
git rm tests/backend/test_play_type_wiring.py

# Edits (closure files + carve package + tests)
git add fresh_slotlab/analyzer/core/base_pipeline.py
git add fresh_slotlab/analyzer/core/parser.py
git add fresh_slotlab/analyzer/play_types/__init__.py
git add fresh_slotlab/analyzer/play_types/bcm_cycle.py
git add fresh_slotlab/analyzer/play_types/wild_nudge.py
git add fresh_slotlab/player_impact_analyzer.py

# Re-pinned base_hash tests
git add tests/analyzer/test_c3_5_isolation_m275_only.py
git add tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py
git add tests/analyzer/test_c5_byte_identical_unrelated_fields.py
git add tests/analyzer/test_c6_byte_identical_bonus_chain.py
git add tests/analyzer/test_c6_carve_completion.py
git add tests/backend/test_analyzer_core_aggregator.py
git add tests/backend/test_analyzer_core_parser.py
git add tests/backend/test_wave_2c_universal_features.py

# Salvaged + gate test
git add tests/backend/test_bcm_cycle_carve.py
```

**Must NOT stage:**
- `configs/machines.json` (pre-existing unrelated change)
- `session_artifacts/` (docs, pre-existing)
- `slot_designer/` (618 pre-existing deletions)
- `cache/` (evidence artifacts, not source)
- `reports/`
- Any `__pycache__/` directories

---

## Verdict: APPROVE-WITH-FIXES

**Blocking:** 1 MINOR fix required — `bcm_cycle.py:112` dangling `BCMBaseAccumulator` docstring reference.

**After that fix, APPROVE.** The implementation is correct:
- The unconditional-inline edit in parser.py is byte-for-byte the old flag-off golden path — verified line by line.
- The byte-identical claim is evidenced for all 7 machines (mode 1) in `cache/_phaseD_tester_*`, independently re-confirmed by this critic.
- The 13 salvaged tests are genuine with 2 discriminating inject-bug proof cases.
- All 8 base_hash pins are updated with documented reason.
- Zero framework symbols survive in production code (one docstring reference aside from the required fix).
- `bcm_bonus_source="config"` held for M279 medium-confidence pilot — the critical L0→L1 identity claim is confirmed.
