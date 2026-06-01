# Commit C1 — Adversarial Review (impl-critic)
> Branch: claude/playtype-rearch. Base: ff5935c (Commit B). Diff: unstaged working tree changes.
> Files reviewed: _detector.py, parser.py (C1 hunks), _base.py, test_play_type_c1_fixes.py, 04_v2.md, critique_commitB.md.
> Reviewer: impl-critic agent. 2026-06-01.

---

## Severity scale: BLOCKER / SERIOUS / MINOR

---

## 1. [SERIOUS] F4 TEST IS TAUTOLOGICAL — The M15 e2e test promised in the header was never written

**Location**: `tests/backend/test_play_type_c1_fixes.py` lines 567–755 (class TestRoundCtxFidelity), and the header comment lines 40–42.

**The claim**: The file header states: "F4 test runs real parse_chunk_response against a real M15 fixture (subprocess spawned for the subprocess-mode coverage)." The class docstring states: "The M15 e2e test covers the divergence case."

**The reality**: There is no M15 test in the file. `_SKIP_NO_M15` and `_M15_AVAILABLE` are defined at lines 83–93 but `_SKIP_NO_M15` is **never applied to any test method** — it is a dead marker. The two actual tests in `TestRoundCtxFidelity` call `parse_chunk_response(..., round_win_rules=None)` (the default). With `round_win_rules=None`, `extract_round_win` returns raw `WinCredits` and `extract_round_payouts` returns raw `PayoutIdToWinAmount` (per `round_win.py` lines 443–448). Therefore `win_amt == raw WinCredits` and `pid_to_win == raw PayoutIdToWinAmount.keys()` — the exact values the old broken code also read. Both tests pass whether or not the fix was applied.

**Why this bites C2**: The entire purpose of FIX 4 (RoundCtx fidelity) is to expose rule-processed values to accumulators on machines like M15 (SettlementWinAmountRule → `win_amt=0` for settlement rounds where raw `WinCredits` is non-zero). The test suite for C1 contains zero coverage of this divergence case. When C2 introduces a real accumulator on M15 that reads `ctx.win_credits` expecting 0 for settlement rounds, there is no existing test to catch a regression if someone reverts or breaks FIX 4. The fix is correct in the code but the claimed test coverage is false.

**Inject-bug proof**: Replace `win_credits=win_amt` (line 2164) with `win_credits=float(r.get("WinCredits") or 0)`. Both F4 tests still pass (WinCredits == win_amt when no rules). The bug is invisible.

---

## 2. [SERIOUS] _plugin_partial_attribution_errors NEVER CONSUMED — EC-4 "report surfaces a warning" is unimplemented

**Location**: `parser.py` lines 2382–2385; `base_pipeline.py` (no match); `player_impact_analyzer.py` (no match).

**The design doc (04_v2.md §13 EC-4)** states: "mark the chunk as `partial_attribution=True` in the chunk dict ... The report surfaces a warning."

**C1 fix** writes `_plugin_partial_attribution_errors` into `_chunk_plugin_partial`, which propagates into the chunk dict via the `**_chunk_plugin_partial` spread at line 2689. This part is correct — the key survives into the chunk dict.

**But**: `grep -rn "plugin_partial_attribution_errors" fresh_slotlab/ player_impact_analyzer.py` — no matches outside `parser.py` and tests. The key is written into the chunk dict but never read by `base_pipeline.py`, `player_impact_analyzer.py`, or any report-construction path. The "report surfaces a warning" claim is not implemented. This means:
- The key sits inert in the chunk dict.
- If a batch of 10 workers each process a chunk with a faulting accumulator, all 10 write the key to their chunk dicts. No operator-visible signal is produced.

**Further**: even the per-chunk key `_plugin_partial_attribution_errors` is a LIST that is set once at post-loop. But if another accumulator's `to_chunk_partial()` returns a key `_plugin_partial_attribution_errors` (name collision), the type-aware merge (line 2320–2336) would handle it as follows: it's a list → `extend()`. Then the post-loop assignment at line 2383 OVERWRITES the merged value entirely (direct dict assignment, not extend). This is a silent key collision bug.

---

## 3. [SERIOUS] _pt_cfg_empty STUB NOT FIXED — Commit B "SERIOUS at Commit C" finding still present

**Location**: `parser.py` lines 1243–1247.

```python
_pt_cfg_empty = _PlayTypeMachineConfig(machine_id="", mode=0)
for _pt_plugin in _active_plugins:
    _robot_accs[_pt_plugin.FEATURE_ID] = _pt_plugin.make_accumulator(_pt_cfg_empty)
```

The Commit B critique (finding #9) rated this SERIOUS-at-Commit-C. The C1 diff does not fix it. This is constructed per robot inside the robot loop — 100 robots = 100 identical stub configs constructed. Every accumulator at C2 that reads `machine_config.machine_id`, `machine_config.mode`, or `machine_config.plugin_configs` will silently receive empty defaults instead of real configuration. Since `plugin_configs` is `{}` in the stub, any per-machine config (e.g., the trigger pay_id for a specific machine) is invisibly absent. **This is load-bearing for C2 correctness.**

---

## 4. [SERIOUS] DICT-VALUED KEYS ALIASED ON FIRST ROBOT — type-aware merge stores dict by reference, not by copy

**Location**: `parser.py` line 2323.

```python
_chunk_plugin_partial[_mk] = list(_mv) if isinstance(_mv, list) else _mv
```

When `_mv` is a `dict`, `isinstance(_mv, list)` is False and the dict is stored **by reference** into `_chunk_plugin_partial`. If the accumulator's `to_chunk_partial()` returns the same dict object on subsequent calls (or the dict is an attribute of the accumulator's internal state), mutations to that internal dict after `to_chunk_partial()` is called will corrupt `_chunk_plugin_partial[_mk]`. This violates the isolation invariant. The inline code at lines 2295+ handles `chunk_cycle_peaks.extend(...)` which avoids this issue because lists are explicitly extended, but no accumulator in Commit B/C1 exercises this path yet. The fix is incomplete: `list(_mv)` copies lists but `_mv` for dicts is stored as-is. When BCMBaseAccumulator writes a dict-valued key (e.g., a payout map), the first robot's dict alias would be mutated by subsequent robot processing if the accumulator reuses internal state.

---

## 5. [MINOR] _plugin_signals_fire_in_st_rounds RECOMPILES REGEX PER CALL — not per ST

**Location**: `_detector.py` lines 247–252, inside `_plugin_signals_fire_in_st_rounds` which is a closure called N_plugins × N_STs times.

```python
pattern = _re.compile(remark_pattern, flags)
```

This compiles the regex fresh on every call. For 10 STs × 1 bonus-remark plugin = 10 compiles of the same pattern. Python's `re.compile` has an internal LRU cache (512 entries by default), so repeated compiles of the same pattern are fast but not free. More importantly, the regex is compiled inside the inner function which is itself defined inside `detect_play_types`, meaning the cached compiled pattern from `ClaimSignature.matches()` (already compiled for the full-sample check) is not reused here.

Additionally, `import re as _re` is inside the closure body — called N_plugins × N_STs times, each costing a `sys.modules` lookup. Minor at Commit B (empty registry), irritant at Commit C with real plugins.

---

## 6. [MINOR] FIRST-ROBOT DICT INITIALISATION INCONSISTENCY — non-list/non-numeric key on first robot gets reference, not deep copy

(Overlaps with finding #4 but is a distinct variant.) On first robot, `_chunk_plugin_partial[_mk] = _mv` when `_mv` is neither list nor int/float nor str-like. A `frozenset`, `tuple`, or nested dict would be stored by reference. While `frozenset` and `tuple` are immutable (safe), `dict` values are mutable (unsafe). The guard `list(_mv)` for lists is a copy; the else branch is a reference for all non-list types. A defensive copy (`dict(_mv)` for dicts) is absent.

---

## 7. [MINOR] test_f1_inject_all_plugins_as_claimants IS MISLABELED — it only tests the fixed path

**Location**: `tests/backend/test_play_type_c1_fixes.py` lines 913–958 (class TestInjectBugEvidence).

The test is named `test_f1_inject_all_plugins_as_claimants_causes_wrong_routing` and lives in `TestInjectBugEvidence`. It claims: "This test shows the BUG state, then verifies the FIX gives the right result." But the test body contains **no monkeypatch** and **no assertion of broken behavior**. It only calls `detect_play_types` with the fixed code and asserts the correct result. This is identical to `TestPerSTRouting.test_two_plugins_route_each_st_to_correct_owner`. A genuine inject-bug test would monkeypatch `_plugin_signals_fire_in_st_rounds` to return `True` unconditionally (simulating the old `claimants = list(matching_plugins)` behavior) and assert the wrong routing, then verify the unpatched code produces correct routing.

The memory file `feedback_adversarial_self_review.md` specifically calls out: "before commit run verify → dump actual numbers → 3-5 adversarial self-questions." The test header's inject-bug recipe ("revert to old all-plugin claimants → both routing tests RED") is stated as a comment but not exercised as code. Inject-bug tests that only document the recipe but don't execute it provide no regression protection.

---

## 8. [MINOR] PROBE RUN FOR ALL REGISTRY PLUGINS, NOT JUST MATCHED — potential cross-plugin state contamination

**Location**: `parser.py` lines 709–712.

```python
for _pt_plugin_pre in _registry_plugins:
    _pre_probe = _pt_plugin_pre.get_probe()
    if _pre_probe is not None:
        _pre_probe.run(_probe_sample, _chunk_parse_state)
```

This runs probes for ALL registered plugins before `detect_play_types` determines which plugins actually match. If Plugin X doesn't match (its `ClaimSignature.matches()` returns False) but it has a `PreParseProbe` that writes a field to `_chunk_parse_state`, that field is set before detection. If Plugin X's probe incorrectly sets `cost_credits_unreliable=True` on a machine where it shouldn't (e.g., a machine that happens to have all-zero `CostCredits` in the probe sample due to all-bonus first robot), the detection for ALL plugins runs with the wrong classification. The Commit B critique noted the pre-existing cc-detection handles this partially, but running every plugin's probe unconditionally introduces an ordering dependency: a plugin's probe must be safe to run on any machine, not just the machines it matches. This constraint is nowhere documented or tested.

---

## 9. [MINOR] TOPO-SORT combined RE-SORT IS REDUNDANT — but correct

**Location**: `_detector.py` lines 460–461.

```python
combined = list(ready) + sorted(newly_ready)
ready = deque(sorted(combined))
```

`sorted(combined)` re-sorts the already-partially-sorted `list(ready)`. Since `ready` is a `deque` maintained in sorted order by construction (initial `sorted()` at line 446–447, and the `sorted(combined)` on each iteration), `list(ready)` is already sorted. Re-sorting is redundant but correct. This is a code-quality issue, not a bug.

---

## 10. [MINOR] win_amt SEQUENCING ASSUMPTION IN COMMENT IS STALE

**Location**: `parser.py` comment lines 2151–2152: "Both `win_amt` and `pid_to_win` are already computed above this block (lines 1566 and 1912 respectively)."

The comment says `win_amt` is at line 1566 and `pid_to_win` at line 1912. Checking the actual code: `win_amt = extract_round_win(r, rules=round_win_rules)` is at line 1587 (not 1566 — the discrepancy is 21 lines). `pid_to_win = extract_round_payouts(...)` is at line 1933 (not 1912 — 21 lines off). These are probably stale line numbers from an earlier draft (before additional lines were inserted above them). The wiring block at line 2136 correctly references `win_amt` and `pid_to_win` as local variables — the sequencing is correct in the code, just the comment's cited line numbers are wrong. Minor but misleading to future readers.

---

## Adjudication of the 5 flagged concerns from critique_commitB

**Finding #1 (topo-sort order)** — FIXED. `_active_plugins` now rebuilt from `_pt_config.active_plugins` FID list via lookup dict. F2 test (TestTopoOrder) is genuine: plugins registered A→B (wrong order), test asserts B fires before A on each round.

**Finding #2 (EC-4 diagnostic not persisted)** — PARTIALLY FIXED. The structured list IS written to `_chunk_plugin_partial`. But it is NEVER READ by any downstream consumer. The design doc's "report surfaces a warning" is not implemented. Finding #2 in this review (SERIOUS).

**Finding #3 (probe-before-detect order)** — FIXED. The ordering is now: all probes first → sync cost_credits_unreliable → then detect_play_types. Correct.

**Findings #4+#5 (RoundCtx fidelity)** — FIXED IN CODE. `win_credits=win_amt` and `authoritative_pay_ids=frozenset(pid_to_win.keys())` are both correct. But the test coverage for the divergence case (SettlementWinAmountRule) is absent (finding #1 in this review, SERIOUS).

**Finding #6 (cross-robot update() overwrites)** — FIXED. Type-aware merge correctly extends lists, adds ints. Dict-valued keys have an aliasing risk (finding #4 in this review, SERIOUS).

**Finding #9 (_pt_cfg_empty stub)** — NOT FIXED. Still present in C1 (finding #3 in this review, SERIOUS).

---

## 10+ Stress Questions

**Q1** [_detector.py:232–233, file:line specific]: On a machine where `cost_credits_unreliable=True`, `_is_paid(r)` always returns True. `bonus_rounds = []` for every ST. A plugin with `required_bonus_remark_pattern="Freespin"` will NEVER claim any ST because `bonus_rounds` is always empty. This means on M10-family machines, bonus-remark-signal plugins (e.g., BCMFreespinPlugin detecting freespin rounds by remark) would not be detected. Is this intended? The design says cc=unreliable means ALL rounds are paid — but M10 machines might still have bonus rounds distinguishable by other means. No test covers this scenario.

**Q2** [test_play_type_c1_fixes.py:571–581]: The `TestRoundCtxFidelity` class docstring says "The M15 e2e test covers the divergence case." `_SKIP_NO_M15` is defined but never applied. Is the M15 test deferred to C2, or was it omitted? If deferred, it must be a C2 prerequisite — without it, the RoundCtx fidelity fix has no automated guard against regression.

**Q3** [parser.py:1243]: `_pt_cfg_empty = _PlayTypeMachineConfig(machine_id="", mode=0)` is constructed per robot inside the robot loop. At C2, `BCMBaseAccumulator(machine_config)` is a concrete class that likely reads `machine_config.mode` to select which detect_cycle_peak threshold applies. With `mode=0`, what threshold does it use? If mode-0 is out-of-range and silently defaults to mode-1 behavior, the byte-identical gate will catch it. If mode-0 is a valid default with different behavior, it will NOT be caught.

**Q4** [parser.py:2320–2336]: A plugin that emits `{"payout_distribution": {"win_band_1": 42, "win_band_2": 7}}` (a dict-valued tally) on every robot — the first robot sets `_chunk_plugin_partial["payout_distribution"] = the_dict_object` (reference, not copy). The second robot's `to_chunk_partial()` returns a NEW dict with the second robot's counts. The merge code hits the `else: _chunk_plugin_partial[_mk] = _mv` branch (dict is not list, not int/float), overwriting with the second robot's counts. Cross-robot dict accumulation is impossible with the current type-aware merge — it silently discards all but the last robot's dict values. No test covers dict-valued plugin partial keys.

**Q5** [parser.py:2378–2385 vs 2320–2336]: If a plugin's `to_chunk_partial()` returns `{"_plugin_partial_attribution_errors": [...]}` (intentional or accidental name collision), the type-aware merge extends it across robots as a list (correct). Then the post-loop assignment at line 2383 `_chunk_plugin_partial["_plugin_partial_attribution_errors"] = _chunk_plugin_attribution_errors` OVERWRITES the plugin-emitted list with only the runtime-exception list. The plugin's own attribution error reporting is silently discarded. No test covers this collision scenario.

**Q6** [_detector.py:274–296]: The per-ST loop iterates over `sorted(observed_spin_types)`. String sort of numeric IDs produces "1", "10", "11", "126", "140", "2", ... — lexicographic, not numeric. This means ST=10 is processed before ST=2. The precedence resolution is independent per ST so order doesn't affect the final `st_map`. But `onboarding_alerts` are appended in lexicographic ST order. Minor cosmetic issue; no correctness risk. However, if there's an ONBOARDING ALERT tie and order matters for the human reviewer, the lexicographic ordering might be confusing ("ST 126 before ST 140 before ST 2").

**Q7** [parser.py:709–712]: When `_probe_sample` is empty (e.g., first robot has no rounds), `CostCreditsReliabilityProbe.run([], ...)` runs against an empty list. The probe checks `len(sample_rounds) < 5: return`. Empty list passes this check (`0 < 5`), so probe returns early, setting nothing. Correct. But if the first robot has exactly 4 rounds with all-zero CostCredits and BetAmount>0, `all_zero=True, any_bet=True` → sets `cost_credits_unreliable=True` with only 4 rounds as evidence. The minimum-sample guard (from the design doc `§4.5: "if len(sample_rounds) < 5: return"`) is borderline: a 5-round sample is very weak evidence. The pre-existing scan at lines 650–664 used 200 rounds. The probe uses the same probe sample (up to 5000), so in practice this is safe for the pre-set guard. But the 5-round guard is fragile: `len(sample_rounds) < 5` means 5 rounds is "enough" — yet 5 all-zero rounds with bet>0 could occur on a normal BCM machine where the first 5 rounds happened to be bonus rounds.

**Q8** [test_play_type_c1_fixes.py:908–910]: `TestInjectBugEvidence` says "These run in-process (not subprocess) using the real parse_chunk_response." But `feedback_integration_test_argv.md` requires subprocess tests for changes to cache routing / sampling parameters. Does C1's wiring change qualify? The C1 changes are in `parse_chunk_response` (pure computation, no sampling or CLI args) — subprocess testing for CLI argv is not relevant here. However, `feedback_perf_claim_needs_e2e_event_stream.md` says "must spawn true subprocess against true fixture." No test in C1 spawns a subprocess. The `_SKIP_NO_M15` marker infrastructure is in place but no subprocess test exists. The memory file violation is partial: in-process tests cover the wiring, but the subprocess path (where the worker fork spawns `player_impact_analyzer.py` as a subprocess) is untested.

**Q9** [parser.py:2136]: The RoundCtx build block is gated on `if use_play_type_plugins and _robot_accs:`. After `_robot_accs.pop(_fid)` in an on_round exception, `_robot_accs` may become empty mid-robot. For subsequent rounds of the same robot, the gate is False (empty dict is falsy) → `_all_round_ctxs` and `_all_rounds_for_accs` stop accumulating. Then at wiring point 4 (on_robot_end), the gate `if use_play_type_plugins and _robot_accs:` is also False — `on_robot_end` never fires for any accumulator on this robot even though some accumulators might still be in `_robot_accs` (only the faulting one was popped). Wait — if only plugin A faults and is popped, `_robot_accs` still has plugin B. B should still get `on_robot_end`. But `_all_round_ctxs` only accumulated rounds up to A's fault. So B gets `on_robot_end([partial rounds], [partial ctxs])` — a truncated view. Is this the correct EC-4 behavior? The design doc says "the accumulator's state is invalid; its to_chunk_partial() returns {} below" — referring to the faulting accumulator, not the surviving ones. Surviving accumulators receiving truncated round lists is silent data loss.

**Q10** [test_play_type_c1_fixes.py:565–755 vs 04_v2.md §8]: The byte-identical gate is mentioned as the automated guard for C2 (§8, §9-rev Phase 1 #16). C1 tests do not exercise byte-identical comparison — that's C2's responsibility. But C1 is load-bearing for C2's byte-identical gate. If `win_credits=win_amt` (FIX 4) causes a float value where accumulators expected int (e.g., a plugin that does `if ctx.win_credits == 500:`), the byte-identical test would catch the value divergence. However, the `RoundCtx` type annotation changed `win_credits: int` to `win_credits: float` (per `_base.py` diff). Any downstream code that does integer arithmetic on `win_credits` (e.g., `ctx.win_credits // bet` for RTP ratio in int domain) silently changes behavior. No test checks that `win_credits` type change is safe for consumer arithmetic.

---

## Memory feedback violations

**`feedback_no_silent_swallow.md`**: PARTIALLY HONORED. EC-4 errors are written to chunk dict (correct). But the key is never read by any downstream consumer — the "durable signal" is written to a dict that no one reads. This is effectively the same as silent swallow at the operator-visible level. The test proves the key exists in the chunk dict but not that it surfaces anywhere meaningful.

**`feedback_perf_claim_needs_e2e_event_stream.md`**: VIOLATED. The file header claims "F4 test runs real parse_chunk_response against a real M15 fixture (subprocess spawned for the subprocess-mode coverage)." The M15 fixture test is missing. The subprocess test is missing. In-process tests with synthetic data pass, but the claimed M15 coverage does not exist.

**`feedback_integration_test_argv.md`**: NOT APPLICABLE for C1 (no argv changes). Not violated.

**`feedback_adversarial_self_review.md`**: PARTIALLY HONORED. `TestInjectBugEvidence.test_f1_inject_all_plugins_as_claimants_causes_wrong_routing` is labeled inject-bug but only tests fixed behavior. The inject-bug recipe is documented in comments but not executed as code. Per the memory file: "is 'structural' real or me being lazy?" — the F1 inject test is lazy (comment-only recipe, not code-exercised).

---

## Code-level bugs / risks

1. **SERIOUS**: `_pt_cfg_empty` stub (machine_id="", mode=0) passed to all accumulators — load-bearing for C2 if any accumulator reads machine_config fields.
2. **SERIOUS**: Dict-valued plugin partial keys stored by reference on first robot; no dict copy. Subsequent accumulator mutations corrupt the chunk partial.
3. **SERIOUS**: `_plugin_partial_attribution_errors` written to chunk dict but never read by any consumer — "report surfaces a warning" unimplemented.
4. **MINOR**: Post-loop direct assignment at line 2383 overwrites any key `_plugin_partial_attribution_errors` already written by a plugin's `to_chunk_partial()`.
5. **MINOR**: `_re.compile(remark_pattern, flags)` inside inner closure; compiled per ST call, not cached.

---

## Test-level gaps

1. **Critical gap**: No M15 (SettlementWinAmountRule) test. F4's claimed divergence-case coverage is absent. `_SKIP_NO_M15` and `_M15_AVAILABLE` are dead infrastructure.
2. **Missing inject-bug proof for F1**: `TestInjectBugEvidence.test_f1_inject...` only tests fixed behavior, not the bug state.
3. **No dict-valued partial key test**: F3 only covers list (extend) and int (+=) merge semantics. Dict merge silently uses last-robot-wins with no test.
4. **No subprocess test**: In-process only; subprocess path (batch worker fork) is untested for any C1 fix.
5. **No test for Q9 scenario**: surviving accumulator + faulted accumulator in same robot → truncated on_robot_end for survivor.

---

## Claim-vs-reality gaps

| Claim | Reality |
|---|---|
| "F4 test runs real parse_chunk_response against real M15 fixture (subprocess spawned)" | No M15 test exists; `_SKIP_NO_M15` never applied; no subprocess call |
| "TestInjectBugEvidence shows the BUG state, then verifies the FIX" | Only tests fixed state; no bug injection in code |
| "feedback_no_silent_swallow.md honored — EC-4 diagnostic in chunk dict" | Key written but never consumed by downstream; effectively silent at operator level |
| "EC-4: report surfaces a warning" (04_v2.md §13) | No report-surfacing code anywhere in `base_pipeline.py` or `player_impact_analyzer.py` |

---

## Edge cases not covered

- **Cost_credits_unreliable + bonus-remark plugin**: with `cost_credits_unreliable=True`, all rounds are classified as paid, `bonus_rounds=[]` for all STs. A plugin with `required_bonus_remark_pattern` can never fire for any ST on these machines.
- **ST with only bonus rounds + non-`_bonus_`-prefixed required_fields**: `paid_rounds=[]`, signal never fires, plugin never claims this ST. May be correct by design but untested.
- **Empty probe sample**: first robot has 0 rounds. `_probe_sample = []`. Probes run on empty list. `CostCreditsReliabilityProbe` returns early (< 5 rounds). `detect_play_types` runs on empty sample → no STs observed → empty config. Plugin wiring block skipped. Silent fallback.
- **Cross-chunk detection drift** (Commit B finding #10, still unfixed): detection re-runs every chunk. If a rare bonus round doesn't appear in chunk 0001's first robot, the machine is detected as pure-paid for that chunk, and the accumulator for the bonus plugin is not instantiated. This produces an inconsistent `st_map` across chunks within the same run.

---

## Verdict

**APPROVE-WITH-FIXES**

C1 correctly fixes all 5 technical bugs identified in critique_commitB (topo-sort, EC-4 persistence, probe ordering, RoundCtx win_credits, RoundCtx pay_ids). The code changes are correct. The implementation is safe to commit.

However, C1 must NOT be treated as C2-ready without the following:

---

## Required fixes before C2

1. **Write the M15 e2e test** (or remove the false claims in the header). The test must call `parse_chunk_response` with `round_win_rules=[SettlementWinAmountRule(...)]` and a fixture round where `WinCredits=500` but `win_amt=0`, then assert `ctx.win_credits == 0.0`. Without this, the most important case for FIX 4 has no regression guard.

2. **Fix `_pt_cfg_empty` stub** before C2 introduces any accumulator that reads `machine_config`. Either (a) pass the real `_pt_config` object from wiring point 1 into the robot loop, or (b) add a guard that raises `NotImplementedError` if an accumulator reads `machine_id` when it's empty string, failing loudly rather than silently using wrong defaults.

3. **Add a `_plugin_partial_attribution_errors` reader** in `base_pipeline.py` (chunk merge) or `player_impact_analyzer.py` (report assembly) that surfaces the structured diagnostic. The current code writes a signal that no one reads — it satisfies the letter of `feedback_no_silent_swallow.md` (key in dict) but violates its spirit (operator sees nothing).

---

## Optional improvements before C2

1. Fix dict-valued partial key aliasing on first robot (add `dict(_mv)` copy branch for dict type in the type-aware merge).
2. Move `import re as _re` to module top in `_detector.py`; cache `re.compile(remark_pattern, flags)` outside the inner loop (one compile per plugin per detection call, not one per ST).
3. Convert `test_f1_inject_all_plugins_as_claimants_causes_wrong_routing` to a genuine inject-bug test by monkeypatching `_plugin_signals_fire_in_st_rounds` to return True unconditionally, asserting the wrong routing, then verifying the correct routing with the real code.
4. Add a test for dict-valued plugin partial merge (assert dict keys from robot 1 are NOT lost when robot 2 returns the same key).
5. Fix stale line number citations in comment at lines 2151–2152 ("lines 1566 and 1912").

---

## Most dangerous issue for C2 byte-identical gate

**Finding #3** (`_pt_cfg_empty` stub) is the most dangerous for C2. Any concrete accumulator at C2 that reads `machine_config.mode` or `machine_config.plugin_configs` silently uses empty defaults. If the byte-identical golden was generated with the real config (via any detection path), and C2's accumulator uses `machine_config.plugin_configs.get("bcm_freespin_pay_id", 666)` and gets 666 by default (when the golden expected a machine-specific value), the byte-identical gate will fail — which is actually the best outcome. The worst outcome is that 666 happens to be the correct default, the gate passes, and the bug lies dormant until a machine with a different trigger pay_id is tested.
