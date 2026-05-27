# Phase C5 — impl-critic critique

> **Date**: 2026-05-27
> **Critic**: impl-critic (claude-sonnet-4-6)
> **Branch**: `claude/analyzer-unbundle-c2`
> **C4 base**: `de46cd0`
> **Verdict**: APPROVE-WITH-FIXES

---

## §1 Verdict

**APPROVE-WITH-FIXES**

Two fixes required before commit. Both are correctness issues in operator-facing text/behavior; neither causes a test failure but one is actively misleading to operators.

---

## §2 Required fixes before commit/merge

**Fix 1 (Required — operator-facing bug)**: The rationale text in `collect_mechanic.py` lines 275-278 is logically incorrect. The `elif current_cst is not None:` branch fires when `current_cst >= recommended_min` (condition `current_cst < recommended_min` is False). The current text says:

```
f"current chunk_spin_times {current_cst} covers at least {int(recommended_safety)} recommended minimum"
```

For M275 actual values: `current=5000`, `recommended_min=5000`, `recommended_safety=7500`. This produces: *"current chunk_spin_times 5000 covers at least 7500 recommended minimum"* — which is grammatically and numerically wrong (5000 does not cover 7500). The operator reading this would be justifiably confused.

The branch should distinguish three sub-cases: (a) `current >= recommended_safety` (adequate), (b) `recommended_min <= current < recommended_safety` (borderline, warn), (c) `current < recommended_min` (too short). Currently only case (c) is correctly labelled; cases (a) and (b) are collapsed into one confusing message. No test catches this because the rationale tests only assert non-empty string and presence of "1000".

**Fix 2 (Required — test comment factual error)**: In `tests/analyzer/test_c3_5_isolation_m275_only.py`, the updated comment says:

```python
# C3.5 value was "f3f2e5b58047" (multiplier_wild only).
# C4 adds machine_mechanics to M275.json → new hash "f3f2e5b58047".
```

This states both C3.5 and C4 produce the same hash `f3f2e5b58047`. That is self-contradictory — adding a plugin must produce a different hash. The actual history is: C3.5 value was `2ef11cd69c8d` (confirmed by the original test text), C4 M275 value was `7489a1582d6d` (per `byte_identical_results.md`), and C5 value is `f3f2e5b58047` (confirmed by `compute_effective_version_for_machine`). The comment is wrong about the C3.5 value, stating it was the C5 value. The assert values are numerically correct (tests will pass), but an engineer reading this comment to understand the version history will be actively misinformed.

---

## §3 Q1 — Stash pattern correctness: ordering + lifetime

Stash keys are written unconditionally in the post-summary block (character offset ~240535 in PIA) before the emit loop begins (character offset ~255176). Verified by direct char-offset comparison: both stashes precede the emit loop. The emit loop is at ~line 5041.

For machines that do NOT declare either plugin, the stash is still written, emit() is not called, and the top-level `_`-key cleanup loop at line ~5082 removes both stash keys. The cleanup loop iterates `list(summary.keys())` and pops any `_`-prefixed key. This is correct.

Lifecycle for declaring machines: stash written → emit() called → `summary.pop(_STASH_KEY)` inside emit() removes it in-situ → cleanup loop finds it already gone (pop with default handles this). The `test_m275_no_stash_keys_in_top_level` and `test_m14_no_stash_keys_in_top_level` tests verify this end-to-end via subprocess.

No ordering risk: both plugins have `REQUIRES = ()`, so topo sort places them in any order relative to each other and to other plugins. The stash is pre-computed before any emit fires.

VERDICT: Correct. No stash race condition possible.

---

## §4 Q2 — Gap #5 filter: mixed PayoutGroupId scenario

Verified by simulation: `payout_group_hits = {'0': 50, '5': 10}` produces `nonzero = {'5'}`, so `status = 'populated'` and the row-building loop runs. This is the correct behavior — a machine with at least one nonzero group ID has real grouping and should be populated.

The threshold semantic is correct: "all zeros" means the set of nonzero keys is empty. Mixed (zero and nonzero) correctly routes to "populated".

One pre-existing (non-C5) behavioral note: in the populated loop, `win_spins_in_group = hits if gid != 0 else 0`. If payout_group_hits keys are stored as strings (e.g., `'0'`), then `gid != 0` is `True` for string `'0'` because `'0' != 0` in Python. This means group 0 rows in a mixed scenario would compute `win_spins_in_group = hits` (not 0), potentially inflating `avg_win_when_hit_x`. This is a pre-existing bug not introduced by C5. Not flagging as a C5 fix.

VERDICT: C5 filter logic correct. Pre-existing type-mismatch in populated branch is out-of-scope.

---

## §5 Q3 — Gap #6 formula choice: avg_paid_spins_per_collect vs avg_spins_between_collects

The brief §2.3 specifies `avg_spins_per_collect` from the `clamp_warning` sub-dict. The implementer used `avg_paid_spins_per_collect` which is `total_paid_sessions / collect_count_total`. The `avg_spins_between_collects` at the top level is `total_spins / collect_count_total` (includes bonus spins).

For BCM cycle sizing, the question is: "how many spins does the robot need to complete a cycle?" The BCM tracks paid spins (CostCredits > 0). Using `avg_paid_spins_per_collect` is the semantically correct denominator for "how many paid spins trigger one collect event." The `avg_spins_between_collects` at top-level includes all spin types and would overestimate the chunk size needed for a complete cycle.

The brief §2.3 explicitly names `avg_spins_per_collect` which maps to the clamp_warning's `avg_paid_spins_per_collect` field. The implementer's choice is correct.

VERDICT: Formula semantically correct. `avg_paid_spins_per_collect` is the right input.

---

## §6 Q4 — payout_groups_status cleanup safety: what does the C2 test actually assert?

The `test_no_temp_key_leaks` in `test_c2_byte_identical_m275.py` (line 172-178) asserts:
```python
for k in pi:
    assert not k.startswith("_"), f"Temp key {k!r} leaked (player_impact)"
```

It checks ALL keys in `player_impact` for `_` prefix. With the original name `_payout_groups_status`, this would fail. With the renamed `payout_groups_status` (no `_`), this test passes. The rename is functionally correct.

The test's name ("no_temp_key_leaks") is slightly misleading — it actually tests "no `_`-prefixed keys in `player_impact`", not "no temp keys" in the generic sense. But the protection it provides is real.

VERDICT: Rename was the correct fix. Test semantics preserved.

---

## §7 Q5 — chunk_spin_times_recommendation rationale: hardcoded format vs derived

The rationale is built via f-string interpolation of `detected_cycle_length`, `avg_spins` (formatted to 2 decimal places), and `recommended_min`/`recommended_safety` (formatted to 0 decimal places). These are derived from the actual measured data, not hardcoded. There is no risk of formula-text drift because the text is constructed from the same variables used in the formula computation.

**However**: the `elif current_cst is not None:` branch (Fix 1 above) produces confusing text when `recommended_min <= current_cst < recommended_safety`. This is the rationale correctness bug identified in §2.

VERDICT: Format is correctly derived. Text logic in elif branch is wrong (Fix 1).

---

## §8 Q6 — 8 plugins in ALL_FEATURES: topo sort risk

Verified: `ALL_FEATURES` contains exactly 8 plugins when all are imported. Both C5 plugins have `REQUIRES = ()`, so they add no new edges to the DAG. The topological sort for 8 nodes is trivially fast (8-node Kahn's algorithm). No cyclic dependency risk introduced.

VERDICT: No topo sort risk.

---

## §9 Q7 — avg_bonus_payout None vs 0.0: frontend impact

Old PIA code (inline lambda): when `bonus_feat` is `None`, `bonus_total = 0.0` (the `if bonus_feat else 0.0` arm), then `0.0 / total_completed_cycles` returns `0.0`. Frontend received `0.0` and displayed `"0"` (a number).

New stash code: when `_cm_bonus_feat is None`, the outer `if _cm_bonus_feat else None` returns `None`. Frontend receives `null`. Frontend renderer at `app.js:6196`: `bcc.avg_bonus_payout != null` is `false` → displays `"—"` (dash).

The dash is semantically more correct than zero (zero implies "bonus pays nothing"; dash implies "N/A, no bonus identified"). This is a positive behavior change.

The behavior change affects any machine where `_cm_bonus_feat` is None — these are machines where `bcm_pairings.json` has no entry and heuristic detection found no bonus feature. M14 is one such machine (no BCM, bonus_feat is None).

No frontend null-deref risk: the frontend uses `!= null` guard before `Number(bcc.avg_bonus_payout)`.

VERDICT: Behavior change is a deliberate improvement. Correctly disclosed by implementer as concern #2. No crash risk.

---

## §10 Q8 — 10-site plugin registration verification

Actual count from grep across all three files:

- `fresh_slotlab/player_impact_analyzer.py`: 6 import lines per plugin × 2 plugins at 3 sites (from-cache, online, emit) = 12 import lines total in PIA (fresh + analyzer fallback paths at each site)
- `fresh_slotlab/analyzer/versioning.py`: 2 import lines per plugin × 2 plugins at 1 site = 4 import lines
- `scripts/validate_manifests.py`: 1 import line per plugin × 2 plugins = 2 import lines

Total: 18 import lines added. The brief says "10 import additions" counting only the primary (non-fallback) import lines at 5 logical sites. Both counts reflect correct implementation.

All 5 sites confirmed registered. The `validate_manifests.py` site uses only the `fresh_slotlab.*` path (no try/except fallback), which matches all other C4 plugins in that file.

VERDICT: 10-site count per brief is accurate if counting primary paths. All 5 logical sites registered.

---

## §11 Q9 — Stale hardcoded value fixes: 5 tests updated correctly?

Verified by running `compute_effective_version_for_machine`:
- `M14 mode 1` → `9f70eade19d5` (matches updated test value)
- `M275 mode 1` → `f3f2e5b58047` (matches updated test value)
- `compute_base_analyzer_version()` → `fa440e3eb5f6` (unchanged, matches test)

The updates are arithmetically correct. However the **comment** in `test_c3_5_isolation_m275_only.py` says `"C3.5 value was f3f2e5b58047"` — this is wrong. The C3.5 value was `2ef11cd69c8d` (the value the comment is replacing). The comment contradicts itself by claiming both C3.5 and the current value are `f3f2e5b58047` (see Fix 2 in §2).

VERDICT: Assert values correct. Comment is factually wrong (Fix 2 required).

---

## §12 Q10 — 127 C5 tests vs 543 total

Counted: 127 test functions across 6 C5 test files (`testpayout_groups_status_not_populated` in `test_c5_m14_no_false_positives.py` and `test_pia_sourcepayout_groups_status_written_to_player_impact` in `test_c5_gap_5_payout_groups_filter.py` use non-standard naming without underscore after "test" but are valid pytest-discoverable functions). Count matches.

The 543 total / 127 new = 416 pre-existing tests. This matches the stated C4-era count of 416.

VERDICT: Test count claim accurate.

---

## §13 Q11 — Commit message facts vs actual diff

Claims to verify:
- Gap #5 closed: YES — `payout_groups_top20 = []` for all-zeros machines, `payout_groups_status` field added
- Gap #6 closed: YES — `chunk_spin_times_recommendation` in `clamp_warning` for applicable machines
- 253 manifest universal rollout: YES — all 253 base manifests modified (verified via `git status` count vs `manifest_schema.json` exclusion)
- 4 inject-bug RED→GREEN: YES — documented in `inject_bug_evidence.md` with specific failing test names
- base_hash unchanged at `fa440e3eb5f6`: YES — verified by running `compute_base_analyzer_version()`
- effective_version flipped for all declaring manifests: YES — M14/M275/M37/M272 all flipped

VERDICT: All commit claims verified against actual diff.

---

## §14 Q12 — Coordinator verifier subsumption defensibility

The coordinator subsumed the impl-verifier ceremony citing 127 tests + byte-identical evidence + inject-bug coverage. This follows the same pattern as C3.5 where verifier was also subsumed.

Blind spots relative to a full verifier ceremony:
1. The rationale text bug (Fix 1) was NOT caught by any test — a human verifier running E2E and reading the output would have caught it.
2. The comment factual error (Fix 2) is similarly not test-caught.
3. The `REGISTERED_FALLBACK_RULES` schema-location mismatch (see §15 Q-beyond-prompted) would not be caught by tests.

For a phase of this complexity (2 plugins + 2 gap fixes), subsumption is borderline defensible. The 2 required fixes both fall into the "human eye catches what tests don't" category.

VERDICT: Subsumption defensible but the two required fixes demonstrate its blind spot.

---

## §15 Q-beyond-prompted (issues not in original stress questions)

**B1 — REGISTERED_FALLBACK_RULES schema location mismatch (low severity)**: `CollectMechanic.REGISTERED_FALLBACK_RULES[1] = {"chunk_spin_times_recommendation": None}`. This key is documented as applying to the `collect_mechanic` top-level dict. But `chunk_spin_times_recommendation` lives inside `collect_mechanic["clamp_warning"]`, not at `collect_mechanic` root. If any runtime consumer (future or current) reads this rule and tries to apply `collect_mechanic["chunk_spin_times_recommendation"] = None`, it would write to the wrong location. Currently there is no runtime consumer — the `REGISTERED_FALLBACK_RULES` attribute has no Python code that reads it (it exists purely as documentation metadata). The risk is future code that implements rule application will have a schema-location bug. Low severity because the system is currently inert, but the misdocumentation could cause a C6/C7 bug.

**B2 — Variant manifests correctly excluded (confirmed, not a bug)**: 166 variant manifests (files with `$` in name) were not modified. This is correct — variants inherit from base manifests. The 253 base machine manifests were all updated. `manifest_schema.json` (the schema file, not a machine manifest) was correctly not modified.

**B3 — "populated" path for payout_groups_top20 untested via subprocess**: No cached machine has nonzero `payout_group_hits`. The test suite covers the "populated" path only via AST/source inspection (checking that the guard string `if payout_groups_status == "populated":` exists in PIA source and that all three status literals are present). The row formatting for the populated path (with real group IDs) is not behavior-tested. This is acknowledged in the test file's docstring. Risk: if the row-building loop for "populated" machines breaks silently, only source inspection tests protect it. Acceptable risk given no populated-status machines exist in cache, but worth documenting.

**B4 — test_pipeline_context.py updated for C4 marker removal**: The diff updates `test_c1_phase_marker` to `test_c4_phase_no_placeholder_marker`. This is a C4 debt fix being bundled into the C5 commit. It's correct (the `_phase: C1_placeholder` marker was removed in C4 real registry) but is technically a C4 test fix, not a C5 test. Low risk — the test now correctly tests the live behavior.

**B5 — M275 current chunk_spin_times vs recommended_min being equal**: For M275, `current = recommended_min = 5000`. The condition `current_cst < recommended_min` is `5000 < 5000` → `False`, so the "too short" message does NOT fire. The elif fires and says the confusing "covers at least 7500" message (Fix 1). The operator looking at M275 specifically receives the wrong message for the exact machine this feature was designed for. This makes Fix 1 high priority.

---

## §16 Stress questions summary

| Q | Assessment | Status |
|---|---|---|
| Q1: Stash ordering + lifetime | Stash before emit; cleanup handles non-declaring machines | PASS |
| Q2: Gap #5 mixed PayoutGroupId | Correctly handles [0,5] as "populated" | PASS |
| Q3: avg_paid_spins_per_collect formula | Semantically correct vs avg_spins_between_collects | PASS |
| Q4: payout_groups_status cleanup safety | C2 test checks player_impact _ prefix; rename correct | PASS |
| Q5: rationale hardcoded vs derived | Derived from formula vars; but elif branch text wrong | FIX REQUIRED |
| Q6: 8-plugin topo sort risk | Both REQUIRES=(). No new edges. No risk | PASS |
| Q7: avg_bonus_payout None vs 0.0 | Positive behavioral change; frontend handles null | PASS |
| Q8: 10-site registration | 5 logical sites all registered; 18 import lines total | PASS |
| Q9: stale value fixes correct | Assert values correct; comment has factual error | FIX REQUIRED |
| Q10: 127 tests count | 127 confirmed (includes non-underscore testXxx names) | PASS |
| Q11: commit msg facts | All claims verified against actual diff | PASS |
| Q12: verifier subsumption | Defensible; two fixes are exactly what verifier would have caught | ACCEPTABLE |

---

## §17 Code-level bugs / risks

1. **Rationale text bug in elif branch** (Fix 1) — operator-facing incorrect text for machines where `recommended_min <= current < recommended_safety`
2. **REGISTERED_FALLBACK_RULES schema location mismatch** (B1) — `chunk_spin_times_recommendation` documented at wrong nesting level; currently inert but future risk
3. **cm["clamp_warning"] = clamp reassignment**: when the stash has a real dict for clamp_warning, `clamp = cm.get("clamp_warning") or {}` gets the same object. `cm["clamp_warning"] = clamp` is then a self-assignment (no-op). Safe. But if `clamp_warning` were `None` in the stash, it would become `{}` in output (schema drift from None to {}). PIA always writes a dict, so this is safe in practice.

---

## §18 Test-level gaps

1. **"populated" payout_groups_top20 row formatting** — only covered by source inspection, not subprocess behavior test. Risk: future row-format bug in the populated branch (which no cached machine exercises) would be silent.
2. **Rationale text correctness** — tests only check non-empty string + "1000" present. The logically incorrect "covers at least" text passes all tests.
3. **clamp_warning=None in stash** — no test verifies the `or {}` guard; safe by construction but untested.

---

## §19 Claim-vs-reality gaps

1. Brief §2.2 acceptance criteria §4 item 3 references `_payout_groups_status` (with underscore) but implementation uses `payout_groups_status`. Coordinator's rename was correct; brief criteria is stale. Not a code bug.
2. Brief §2.3 states `avg_spins_per_collect` estimated at 5.57 (→ recommended_min 5570). Actual measured value is 5.0 (→ recommended_min 5000). `byte_identical_results.md` correctly documents this discrepancy.
3. Comment in `test_c3_5_isolation_m275_only.py` says `"C3.5 value was f3f2e5b58047"` which is incorrect — that's the C5 value, not the C3.5 value.

---

## §20 Edge cases not covered

1. Machine with `payout_group_hits` containing only negative group IDs (e.g., `{-1: 5}`) — `int('-1') != 0` is `True`, status = "populated". Behavioral correctness depends on whether negative IDs are valid. Pre-existing, not C5 scope.
2. `avg_paid_spins_per_collect = 0.0` (nonzero collect count, zero paid sessions) — blocked by `avg_spins > 0` guard in collect_mechanic emit(). Correctly handled.
3. `detected_cycle_length = 0` (impossible mathematically but defensive) — `0 * avg_spins = 0` → `recommended_min = 0`, `recommended_safety = 0`. Would produce a nonsensical recommendation but wouldn't crash.

---

## §21 Memory feedback violations: 0

All cited memory files honored:
- `feedback_no_silent_swallow.md`: both plugins raise `RuntimeError` on missing stash
- `feedback_invariant_with_fallback_hides_drift.md`: `payout_groups_status` is explicit named enum; `chunk_spin_times_recommendation` absent (not zero) when not applicable
- `feedback_subprocess_import_suicide_and_module_globals.md`: `register()` is pure list-append at import time; no I/O
- `feedback_no_hardcode.md`: no machine-specific constants in plugins
- `feedback_prefer_complex_better.md`: stash pattern reused from BankruptcySimulation
- `feedback_enumerate_safety_paths.md`: 4 inject-bug cycles documented

---

## Summary

- File written: `session_artifacts/_impl/phase_c5/critique.md`
- Verdict: **APPROVE-WITH-FIXES**
- Required fixes: 2
  1. Fix rationale text in `collect_mechanic.py` elif branch (currently says "covers at least 7500" when current is between min and safety — logically wrong)
  2. Fix comment in `test_c3_5_isolation_m275_only.py` (says C3.5 value was `f3f2e5b58047` which is the C5 value)
- Biggest concern: The rationale text bug (Fix 1) is the operator-facing output for the M275 machine that drove this entire phase, producing a confusing "5000 covers at least 7500" statement
- Beyond prompted: `REGISTERED_FALLBACK_RULES[1]` key `chunk_spin_times_recommendation` is at the wrong schema level (top of collect_mechanic, not inside clamp_warning) — currently inert but a future application bug
- Confidence ready to commit after fixes: HIGH — core logic correct, tests solid, all stash/cleanup/registration plumbing verified
