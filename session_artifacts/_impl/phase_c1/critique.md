# Phase C1 — impl-critic Critique

> Critic: impl-critic (Claude agent)
> Date: 2026-05-25
> Verdict: **APPROVE-WITH-FIXES** (2 required fixes, both <20 lines each)

---

## §1 Verdict Statement

**APPROVE-WITH-FIXES.**

The core infrastructure (PipelineContext, ParseState, topo_sort, emit signature change, extract() wiring) is correctly implemented and produces byte-identical output on M14 and M275. Two fixes are required before commit:

1. **FIX-1 (HIGH)**: `_feature_errors` dict is silently swept into oblivion by the `_`-prefix cleanup loop. Emit errors are swallowed from the final JSON. Rename to `feature_errors` (no underscore) or exclude it from the sweep. Violates `feedback_no_silent_swallow.md`.

2. **FIX-2 (MEDIUM)**: `test_main_source_contains_feature_emit_call` in `tests/backend/test_wave_2c_universal_features.py` was PASSING pre-C1 and is FAILING post-C1. C1 changed the loop from `for _feature in ALL_FEATURES:` to `for _feature in _sorted_features:` but did NOT update the regex test that searches for `for <var> in ALL_FEATURES:`. This is a C1-caused regression in the test suite, not a pre-existing failure as the verifier claimed.

One additional item is flagged as MEDIUM concern requiring doc/follow-up but not a blocking fix:

3. **CONCERN-3 (MEDIUM)**: `analyzer_init_error` is written to `summary` dict but `SystemExit(1)` fires before `write_summary_json()`. The key never reaches disk. Spec §4.2 says "written to summary" — ambiguous. Acceptable as APPROVE-WITH-FIXES if: (a) verifier's interpretation of "stderr + rc=1 is the canonical signal" is recorded explicitly in the commit message Self-critique section, and (b) FIX-1 + FIX-2 are resolved. If the intent is disk write, add a sidecar write before `SystemExit`.

---

## §2 Required Fixes Before Commit/Merge

**FIX-1**: `fresh_slotlab/player_impact_analyzer.py` — `_feature_errors` is swept by `for _tmp_key: if startswith("_")` cleanup at line ~5060.

Change `_feature_errors` to `feature_errors` (no underscore) in both the set site (line ~5051-5053) and the comment (line ~5033). This key must survive to the JSON write so operators can see which plugin crashed. Without this fix, an emit() failure in any plugin is completely invisible in the final report — no key in summary, only stderr text which is not guaranteed to be captured in the batch log.

**FIX-2**: `tests/backend/test_wave_2c_universal_features.py:516-554` — `test_main_source_contains_feature_emit_call` regex searches for `for <var> in ALL_FEATURES:` which no longer exists in PIA. The test now fails with `AssertionError: No 'for <var> in ALL_FEATURES:' loop found`. Update the regex to match `for <var> in _sorted_features:` or broaden to match either. The test's PURPOSE (verify the emit loop exists in main()) is still valid — only the pattern needs updating.

---

## §3 Stress Question 1: `analyzer_init_error` — In-Memory Only?

**Question**: Brief §4 AC-5 says "write `summary["analyzer_init_error"] = {...}`... return non-zero exit code". Does "write" mean write-to-dict or write-to-disk?

**Evidence**: 
- `fresh_slotlab/player_impact_analyzer.py:5020`: `summary["analyzer_init_error"] = _topo_error_dict`
- `fresh_slotlab/player_impact_analyzer.py:5027`: `raise SystemExit(1) from _topo_exc`
- `fresh_slotlab/player_impact_analyzer.py:5155`: `out_json = write_summary_json(summary, args.output_dir)` — this comes AFTER SystemExit fires.

The SystemExit at line 5027 is caught by the Python interpreter, not by any inner try/except in main(). The `write_summary_json` call at line 5155 is never reached. The summary dict with the key exists only in memory and is garbage-collected.

**Spec says (04_v3 §4.2)**:
```
3. On catch, PIA:
   - Writes a structured diagnostic to summary["analyzer_init_error"] (new top-level summary field)
   - Logs to stderr at ERROR level
   - Exits with a non-zero return code
4. The console UI surfaces summary.analyzer_init_error if present.
```

Point 4 ("UI surfaces it if present") implies it must reach disk so the backend can load the summary and pass it to the UI. The current implementation satisfies points 1-3 but NOT point 4.

**Severity**: MEDIUM. In C1 it is a no-op concern because no real cyclic dep exists yet. When C2-C6 introduce REQUIRES edges, a misconfiguration would produce a failed run with no diagnostic in the UI — operator would see a failed run with no details.

**Recommendation**: Accept for C1 with explicit disclosure in the commit message Self-critique section. In C2, add partial JSON write before SystemExit (or write a `<output_dir>/analyzer_init_error.json` sidecar). Do not block C1 on this.

---

## §4 Stress Question 2: Byte-Identical Scope Sufficient?

**Question**: Tester ran M14 mode 1 and M275 mode 1. Verifier ran 5 machines but all mode 1. Are other modes tested?

**Evidence**:
- `session_artifacts/_impl/phase_c1/byte_identical_results.md`: only mode 1 rows in the table.
- `fresh_slotlab/player_impact_analyzer.py:1989`: manifest passed to ParseState is `{}` (empty dict) in the extract() call during the merge loop. This is correct — manifest is not yet loaded at that point. Same in the online path at line 2746.
- The emit path loads the manifest (line 4946) and passes it to `PipelineContext`. This is mode-specific.

**Concern**: The `_c1_manifest = _c1_resolve_per_mode(_c1_manifest, args.rtp_mode)` call at line 4949 applies per-mode filtering. If `resolve_per_mode` has any side effect on the dict structure that differs between mode 1 and mode 2, a per-mode behavioral difference could exist. However, since all 4 plugins are Pattern A (emit is a no-op assertion), and the BankruptcySimulation only reads `_bankruptcy_rows` from summary (not from ctx.manifest), no visible output change should occur across modes.

**Verdict on scope**: Acceptable. Pattern A plugins don't use ctx at all. BankruptcySimulation doesn't use ctx.manifest. Mode 2/5/7 testing would add certainty but the code path analysis confirms mode cannot matter for C1 plugins.

**Severity**: LOW. The reasoning is sound. Flag for C2+ when plugins actually USE ctx.manifest.

---

## §5 Stress Question 3: Test Debt — Who Caused `test_main_source_contains_feature_emit_call` Failure?

**Question**: Verifier said this test was "pre-existing before my changes". Is that accurate?

**Evidence**:
- `git show HEAD:fresh_slotlab/player_impact_analyzer.py | grep "for _feature in ALL_FEATURES:"` → returns 1 match. Pre-C1 committed state HAS the `ALL_FEATURES` loop.
- Post-C1 diff removes `for _feature in ALL_FEATURES:` and replaces with `for _feature in _sorted_features:`.
- `tests/backend/test_wave_2c_universal_features.py:541`: regex `r'for\s+(\w+)\s+in\s+ALL_FEATURES\s*:'` now fails to match.
- Running the test post-C1: `FAILED tests/backend/test_wave_2c_universal_features.py::TestMainInvokesFeatureEmit::test_main_source_contains_feature_emit_call` — confirmed by actual pytest run.

**Finding**: The verifier's claim that this is "pre-existing" is INCORRECT. Pre-C1 HEAD passes this test. C1 broke it by replacing the ALL_FEATURES loop. This is a C1-caused regression.

**Severity**: HIGH. The test suite now has a C1-caused failing test that the verifier misattributed as pre-existing. This blocks commit. See FIX-2 above.

---

## §6 Stress Question 4: MechanismRegistry Placeholder — Safe for C2-C6 Transition?

**Question**: Between C1 and C4, any plugin reading `ctx.mechanism_registry.jackpot_applicable` sees `False`. Is this safe?

**Evidence**:
- `fresh_slotlab/analyzer/pipeline_context.py:53-61`: all fields are `False` / empty frozensets.
- C1 plugins (Pattern A) do NOT read ctx at all in their emit() bodies.
- BankruptcySimulation does NOT read ctx.mechanism_registry.
- No C1 plugin uses the registry.

**C2-C3 risk**: C2 promotes `payouts_by_spin_type` to Pattern B. If the implementer accidentally reads `ctx.mechanism_registry.jackpot_applicable` in C2's emit() before C4 ships real detection, they'll get `False` and produce wrong panels silently. There's no compile-time guard.

**Mitigation present**: The docstring on MechanismRegistry states "All attributes return empty / falsy values, making mechanism-registry-aware emit() plugins degrade gracefully to their current (pre-C4) fallback behaviour." This is intentional design. The C2-C3 implementer must be briefed NOT to gate on registry fields until C4.

**Verdict**: Acceptable as design. The placeholder is correctly documented. The risk is an implementer mistake in C2-C3, not a C1 defect. Flag in the C2 brief.

**Severity**: LOW for C1 scope.

---

## §7 Stress Question 5: DECLARED_DEPS ClassVar — Enforcement Exists or Just Declaration?

**Question**: `DECLARED_DEPS` is declared on the ABC. Is it validated at runtime in C1?

**Evidence**:
- `fresh_slotlab/player_impact_analyzer.py:5035-5043`: before each plugin's `emit()`, the loop checks:
  ```python
  for _dep_key in _feature.DECLARED_DEPS:
      if _dep_key not in summary:
          raise RuntimeError(...)
  ```
- BankruptcySimulation declares `DECLARED_DEPS = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")`.
- These are stashed in summary at lines 4871-4872 before the emit loop.
- The validation check fires and will `raise RuntimeError` if keys are missing.

**Critical finding**: The `raise RuntimeError` at line 5039 is OUTSIDE the `try/except Exception` block that wraps `_feature.emit()`. The RuntimeError propagates uncaught through the emit loop and through main(), ultimately crashing the process without writing `summary["analyzer_init_error"]` and without a clean rc=1 + structured diagnostic. It gets handled by Python's default exception handler (prints traceback to stderr + rc=1), but the summary is not written to disk.

This is inconsistent with the spec (§4.2): "DECLARED_DEPS missing key: RuntimeError at emit-loop start (programming error)" — the spec says RuntimeError but doesn't say it should be unhandled. Since the topo-sort errors are handled with `summary["analyzer_init_error"] + SystemExit(1)`, the missing-dep RuntimeError should receive the same treatment.

**Severity**: MEDIUM. In C1, BankruptcySimulation's deps are always present (stashed before the loop). This cannot fire in C1. It becomes a real risk in C2+ if any plugin declares DECLARED_DEPS that aren't stashed. Could be left as-is for C1 with a flag for C2.

---

## §8 Stress Question 6: BankruptcySimulation Pattern B — Hidden Temp-Key Contract Preserved?

**Question**: Does C1 still stash `_bankruptcy_rows` + `_bankruptcy_sim_session_spins` before the emit loop fires?

**Evidence**:
- `fresh_slotlab/player_impact_analyzer.py:4871-4872` (in the diff): these two lines appear BEFORE the feature loop and BEFORE the import block:
  ```python
  summary["_bankruptcy_rows"] = bankruptcy_rows
  summary["_bankruptcy_sim_session_spins"] = bankruptcy_sim_session_spins
  ```
- The stash is unconditional — fires for every machine, even those without BankruptcySim in their manifest.
- BankruptcySim.emit() at line 5044 reads these via `summary["_bankruptcy_rows"]` with no null guard.
- If a machine's manifest does NOT include `bankruptcy_simulation` in `analyzer_features`, `get_features_for_machine` excludes it, so emit() is never called, and the stashed keys are swept in the cleanup loop (line 5060). No problem.
- If a machine HAS BankruptcySim in its feature list, the stash is present. BankruptcySim.emit() runs and deletes the temp keys. Cleanup loop finds them already deleted — harmless (uses `summary.pop(_tmp_key, None)`).

**Verdict**: PASS. The stash/cleanup sequence is preserved correctly.

**Severity**: No issue.

---

## §9 Stress Question 7: Topo Sort Tiebreaking — Deterministic?

**Question**: Is the tiebreaking in `topo_sort.py` actually deterministic across Python versions?

**Evidence**:
- `fresh_slotlab/analyzer/topo_sort.py:150-175`: Initial queue sorted by FEATURE_ID. After each node is processed, newly-ready nodes are added with `combined = list(ready) + sorted(newly_ready); ready = deque(sorted(combined))`.
- The inner `sorted(combined)` re-sorts the ENTIRE ready deque on every step, not just the newly-added nodes.
- This is O(n²log n) per layer but correct for small feature sets (<20 plugins per spec).
- Python's `sorted()` is stable and deterministic for strings. String comparison is byte-by-byte, which is invariant across Python versions for ASCII feature IDs.

**Subtle concern**: The tiebreak works because all 4 current FEATURE_IDs are ASCII strings. If a future plugin uses a non-ASCII FEATURE_ID (unlikely but possible), Unicode collation could theoretically differ, though Python's `str.__lt__` uses codepoint ordering which is stable.

**Verdict**: Acceptable. Stable for all foreseeable plugin IDs. The deque re-sort on every step is slightly wasteful but correct.

**Severity**: LOW (informational for C2+).

---

## §10 Stress Question 8: `ParseState` Usage — Actually Called?

**Question**: Is `extract()` actually wired in both merge paths?

**Evidence**:
- From-cache path: `fresh_slotlab/player_impact_analyzer.py:1968-2001` — block after `total_dollar_pick_win` accumulation, before the heartbeat emit. Imports `ALL_FEATURES` + `ParseState`, builds `_fc_ParseState(chunk_dict=rec, machine_id=args.machine, mode=args.rtp_mode, manifest={})`, then `for _fc_feat in _fc_features: _fc_this = _fc_feat.extract(_fc_parse_state, rec); _feature_accs[...] = _fc_feat.reduce(...)`.
- Online path: `fresh_slotlab/player_impact_analyzer.py:2730-2763` — identical structure, different variable prefix (`_ol_` vs `_fc_`).

**Critical observation**: Both paths pass `manifest={}` (empty dict) to ParseState. The docstring says this is intentional ("manifest not yet loaded; plugins don't use it in extract()"). This is correct for C1. Pattern A plugins return `{}` and ignore both `parse_state` and `chunk_dict`.

**But**: The `_feature_accs` dict initialized at line 1411 is `{}` (empty dict with no default). The pattern `_feature_accs.get(_fc_feat.FEATURE_ID, {})` correctly handles first-access by returning `{}` as the initial acc. On the next reduce, `prev_acc = {}` is passed. Since all Pattern A plugins return `prev_acc` unchanged from `reduce()`, `_feature_accs[fid]` remains `{}` for all features. This is harmless in C1 but means the extract() → reduce() → emit() pipeline is exercised only in the "no-op" path.

**Verdict**: Both paths are wired. Correct behavior for C1.

---

## §11 Stress Question 9: Frozen PipelineContext — Deep Immutability?

**Question**: `frozen=True` prevents attribute reassignment on PipelineContext, but can a plugin mutate `ctx.manifest["new_key"] = ...`?

**Evidence**:
- `fresh_slotlab/analyzer/pipeline_context.py:83`: `@dataclass(frozen=True)`. This prevents `ctx.manifest = {...}` but does NOT prevent `ctx.manifest["new_key"] = "value"` because `dict` is a mutable object and frozen only blocks setattr.
- `tests/analyzer/test_pipeline_context.py:141-158`: Tests only check that `ctx.total_spins = 99` raises, `ctx.new_field = "x"` raises, and `ctx.mechanism_registry = new_mr` raises. No test for `ctx.manifest["x"] = "y"`.
- `MechanismRegistry` is also mutable: `ctx.mechanism_registry.jackpot_applicable = True` would succeed silently.

**Current risk in C1**: Zero. No plugin touches ctx.manifest or ctx.mechanism_registry in C1.

**Future risk (C2+)**: If a plugin in C2 does `ctx.manifest["my_cache_key"] = result` to store intermediate results, subsequent plugins see the mutation. This is a latent footgun.

**Recommendation**: Accept for C1 with a TODO in the MechanismRegistry docstring advising subclasses not to mutate ctx.manifest at emit() time. A deep-freeze helper is out of scope for C1.

**Severity**: LOW for C1 scope.

---

## §12 Stress Question 10: Commit Message — Accurate Post-Impl?

**Question**: Does the draft commit message accurately reflect what was implemented?

**Evidence** from `brief.md §9` draft:
- "M14 + M275 cached rebuilds byte-identical pre/post" — ACCURATE.
- "analyzer_init_error surfacing path (summary key + stderr + non-zero rc)" — PARTIALLY ACCURATE. The key is written to the in-memory dict but never reaches disk. The message implies it functions as a disk-persisted diagnostic.
- "effective_analyzer_version flips for 253 machines (expected, by design)" — ACCURATE.
- Does NOT mention: `_feature_errors` cleanup bug (FIX-1).
- Does NOT mention: `test_main_source_contains_feature_emit_call` C1-caused failure (FIX-2).
- Does NOT mention: `analyzer_init_error` disk-write gap.
- "## Self-critique section" is blank placeholder `[impl-critic fills this section]`.
- Also not mentioned: machines.json and slot_designer/configs/machines_virtual.json changes in the diff — these appear to be MD5 drift from pre-existing work, NOT C1-scope changes.

**Severity**: MEDIUM. The commit message understates known gaps. Self-critique section must be filled before commit.

---

## §13 Stress Question 11: Acceptance Criterion 5 — Subprocess-Level Proof?

**Question**: Brief §4 AC-5 requires "inject test that registers a cyclic plugin pair; assert `summary["analyzer_init_error"]` present + stderr logged + rc != 0". Is unit-level proof acceptable?

**Evidence**:
- `tests/analyzer/test_c1_init_error_surfacing.py` tests the `topological_sort()` function directly (unit test), NOT via subprocess.
- The docstring at line 10-17 of that file explicitly explains why subprocess was not attempted and defers it to Phase C2.
- `memory/feedback_perf_claim_needs_e2e_event_stream.md` (per the brief §5) says "must spawn real subprocess against cached fixture" for subprocess-mode changes.
- The verify-by-subprocess requirement specifically applies when "subprocess-mode bugs" could mask unit-test passing. Here, the topo sort is pure logic — subprocess would add nothing to the function-level test.
- BUT: `summary["analyzer_init_error"]` disk presence can only be verified by subprocess. Since we've now confirmed it's NEVER written to disk (analyzer_init_error is in-memory only, SystemExit fires before write), a subprocess test would have CAUGHT this gap.

**Finding**: The acceptance criterion specifies `summary["analyzer_init_error"] present` — in a subprocess test, this would check the output JSON on disk. The test does NOT exercise this. A subprocess-level test would have revealed that the key is never in the on-disk JSON because SystemExit fires first. This is a coverage gap.

**Severity**: MEDIUM. The unit test verifies the correct exception type but does not verify the disk-write contract. Acceptable for C1 as-is if commit message discloses the disk-write gap.

---

## §14 Stress Question 12: Out-of-Scope Changes in the Diff?

**Question**: Does `git diff HEAD --stat` show changes beyond C1 scope?

**Evidence**:
```
configs/machines.json          | 1352 ++++++++++++++++----
session_artifacts/M43/user_brief.md  |  375 ++++++
slot_designer/configs/machines_virtual.json  |   12 +-
reports/M14/mode_1/index.json  |  104 +-
reports/M14/mode_1/latest.json |   23 +-
```

- `configs/machines.json`: 1352-line change. Inspection shows only `codeSummaryMd5` changes — fleet-wide MD5 update consistent with a prior sampling session, NOT C1-caused. This should NOT be committed in the C1 commit.
- `session_artifacts/M43/user_brief.md`: 375-line addition — M43 slot design session artifact. Entirely unrelated to C1. Must NOT be committed in C1.
- `slot_designer/configs/machines_virtual.json`: MD5 changes for M43 virtual machines. Unrelated to C1.
- `reports/M14/mode_1/index.json` + `latest.json`: Updated M14 report index from the test runs. These are output artifacts of running the analyzer during testing, not C1 code. Should not be committed in C1.

**Finding**: The git diff contains at least 4 files that are clearly outside C1 scope. The coordinator must stage only the C1-relevant files. If committed as-is, the commit mixes C1 plumbing with unrelated MD5 drift, M43 design artifacts, and report outputs.

**Severity**: HIGH for commit hygiene. The code changes are correct but the staged set is polluted. The coordinator must use explicit `git add` for each C1 file rather than `git add -A`.

---

## §15 Commit Message Review

**Current draft** (brief §9 template):
```
refactor(analyzer): C1 — wire extract() + PipelineContext + topo-sort + dep classes

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_v3.md.

Plumbing only — no visible analyzer output change. M14 + M275 cached
rebuilds byte-identical pre/post.
...
## Self-critique (adversarial review)
[impl-critic fills this section before commit]
```

**Required edits to commit message**:

| Claim | Status |
|---|---|
| "M14 + M275 cached rebuilds byte-identical" | GREEN — verified |
| "analyzer_init_error surfacing path" | YELLOW — disk-write gap; must disclose |
| "BankruptcySimulation verified byte-identical" | GREEN |
| "effective_analyzer_version flips for 253 machines" | GREEN |
| Self-critique section | RED — must be filled |
| No mention of test regression (test_main_source) | RED — FIX-2 must be done first OR explicitly acknowledged |
| No mention of out-of-scope files in diff | RED — coordinator must stage only C1 files |

**Self-critique section must include at minimum**:
1. `analyzer_init_error` is written to summary dict but NOT to disk (SystemExit fires before write_summary_json). Stderr + rc=1 are the actionable signals. UI can only surface it if backend catches rc=1 and marks run failed.
2. `_feature_errors` temp key is swept by `_`-prefix cleanup — emit errors are invisible in the final JSON (FIX-1 resolves this).
3. `test_main_source_contains_feature_emit_call` was C1-caused, not pre-existing (FIX-2 resolves this).
4. DECLARED_DEPS missing-key RuntimeError is unhandled — propagates as uncaught exception in C2+ if any plugin's stash is missing. C1-safe because BankruptcySim deps are always present.
5. Out-of-scope files (machines.json, M43 brief, report index) must be excluded from the C1 commit.

---

## §16 Additional Findings Beyond 12 Prompted Questions

### Finding A: Outer `except Exception: pass` in the extract() blocks is `feedback_no_silent_swallow.md` violation

**File**: `fresh_slotlab/player_impact_analyzer.py:2001-2002` (from-cache path) and `2762-2763` (online path):
```python
except Exception:  # noqa: BLE001
    pass
```

This is the OUTER catch — the entire extract/reduce block for ALL features is wrapped in a silent `except: pass`. If `ALL_FEATURES` import fails, `ParseState` import fails, or any feature registration fails, the entire extract phase is silently skipped. No log, no stderr, no summary key.

This is exactly the pattern condemned in `memory/feedback_no_silent_swallow.md`. The comment says "extract() / reduce() error: use prev_acc unchanged" but the outer block catches EVERYTHING including import errors.

Per the spec (§4.2): "extract() errors: log + return {}". Logging is missing. The outer `pass` is a silent swallow of potentially meaningful errors.

**Severity**: MEDIUM. In C1 all plugins have no-op extract() so this cannot fire. In C2+ when plugins actually do work in extract(), an import error or module-level bug would be silently ignored across all 10k+ chunks.

**Recommendation**: The inner per-feature try/except should log at minimum. The outer try/except should at minimum print to stderr. Fix in C1 or note explicitly in the C2 brief.

### Finding B: Double manifest load in finalization block

`fresh_slotlab/player_impact_analyzer.py` now loads the manifest TWICE in the finalization block:
- First load at lines 4940-4950 (C1 Step 1: for PipelineContext)
- Second load at lines 5086-5109 (Phase 5 RTP integrity gate)

Both loads use `_DEFAULT_MANIFEST_ROOT` and the same `args.machine` / `args.rtp_mode`. This is a performance redundancy (two disk reads of the same file). Not a correctness issue, not a C1 blocker. Flag for cleanup in C3 or C4 when the manifest is loaded once and shared.

**Severity**: LOW (informational).

### Finding C: `assert` statement in production code path (Phase C1 ordering sentinel)

`fresh_slotlab/player_impact_analyzer.py:4958-4961`:
```python
assert "spin_type_breakdown" in summary.get("player_impact", {}), (
    "PHASE C1 INVARIANT: F1 inline must write player_impact.spin_type_breakdown ..."
)
```

Python's `assert` is stripped when running with `-O` (optimize flag). This is a production ordering invariant — if it fires in optimized mode, the failure is silent. Should be an explicit `if ... raise` guard.

**Severity**: LOW. Python `-O` is never used in this codebase (subprocess is invoked as `sys.executable script.py` per the test fixtures). But it's a footgun.

### Finding D: `configs/machines.json` codeSummaryMd5 flip is NOT a C1 artifact

The 1352-line change to `configs/machines.json` shows `codeSummaryMd5` changing from `536fc5a2a8f2ecf1fd8c6dfcf2c025cc` to `f7a4cefda016a02849ae8d1711b1939a` fleet-wide. This is consistent with a prior test sampling session updating MD5s — NOT caused by C1. If committed in the C1 commit, it conflates MD5 bookkeeping with the C1 plumbing refactor. Per `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`, this is data not code. Stage it separately.

### Finding E: `slot_designer/configs/machines_virtual.json` M43 changes

Two virtual machine entries have their `configSummaryMd5` changed — one for M43 (`cd2a12...` → `f81b03...`) and one for the M275 virtual (`7fa4ee...` → `fd4e7a...`). These are M43 slot design session artifacts unrelated to C1. Must be excluded.

---

## Summary: All Issues by Severity

| # | Severity | File | Issue | Action |
|---|---|---|---|---|
| FIX-1 | HIGH | player_impact_analyzer.py:5051-5053 | `_feature_errors` swept by `_`-prefix cleanup → emit errors silently discarded | Fix in C1 |
| FIX-2 | HIGH | test_wave_2c_universal_features.py:541 | `test_main_source_contains_feature_emit_call` was passing pre-C1, fails post-C1; regex searches for deprecated `ALL_FEATURES` loop | Fix in C1 |
| CONCERN-3 | MEDIUM | player_impact_analyzer.py:5020,5027,5155 | `analyzer_init_error` never written to disk (SystemExit before write_summary_json) | Accept with disclosure in commit msg |
| CONCERN-A | MEDIUM | player_impact_analyzer.py:2001,2762 | Outer `except: pass` in extract() blocks silently swallows import errors | Flag for C2; accept in C1 (no-op extract) |
| CONCERN-7 | MEDIUM | player_impact_analyzer.py:5035-5043 | DECLARED_DEPS missing-key RuntimeError is unhandled — crashes run without structured diagnostic | Accept for C1 (BankruptcySim deps always present); fix in C2 |
| Q4 | LOW | pipeline_context.py | MechanismRegistry false-until-C4 could cause wrong panels if C2 implementer reads registry | Accept; document in C2 brief |
| Q9 | LOW | pipeline_context.py | ctx.manifest + ctx.mechanism_registry are not deeply frozen | Accept; note in C2 brief |
| FINDING-B | LOW | player_impact_analyzer.py | Double manifest load in finalization block | Informational; clean up in C4 |
| FINDING-C | LOW | player_impact_analyzer.py:4958 | assert for ordering sentinel (stripped by -O) | Low risk; fix when convenient |
| FINDING-D | HIGH (commit hygiene) | configs/machines.json | 1352-line MD5 drift unrelated to C1; must be excluded from C1 commit | Stage separately |
| FINDING-E | HIGH (commit hygiene) | machines_virtual.json, M43/user_brief.md, reports/ | Out-of-scope artifacts in diff | Exclude from C1 commit |

---

## Required Fixes Before Commit/Merge (Numbered)

1. **Rename `_feature_errors` to `feature_errors`** in `fresh_slotlab/player_impact_analyzer.py` at lines ~5033, ~5051, ~5052, ~5053 so emit errors survive the `_`-prefix cleanup and appear in the final JSON.

2. **Update regex in `tests/backend/test_wave_2c_universal_features.py:541`** to match the new `_sorted_features` loop variable instead of `ALL_FEATURES`. Change pattern from `r'for\s+(\w+)\s+in\s+ALL_FEATURES\s*:'` to something like `r'for\s+(\w+)\s+in\s+(_sorted_features|ALL_FEATURES)\s*:'` or `r'for\s+(\w+)\s+in\s+_sorted_features\s*:'`.

3. **Exclude out-of-scope files from C1 commit**: `configs/machines.json`, `slot_designer/configs/machines_virtual.json`, `session_artifacts/M43/user_brief.md`, `reports/M14/mode_1/index.json`, `reports/M14/mode_1/latest.json`. These must NOT be in the C1 commit. Stage only: the 3 new files + 6 modified analyzer files + 5 new test files + `tests/backend/test_wave_2c_universal_features.py`.

4. **Fill Self-critique section** in the commit message per the template, disclosing the `analyzer_init_error` disk-write gap, the `_feature_errors` fix, and the test update.

## Optional Improvements (Non-Blocking)

1. Add `print(f"[C1 extract warning]...", file=sys.stderr)` inside the outer `except: pass` blocks at lines 2001 and 2762 to give at least some signal on import failure.
2. Convert the `assert` at line 4958 to `if ... raise RuntimeError(...)` for `-O` safety.
3. Add a TODO in the PIA finalization comment about double manifest load.
4. Add a subprocess-level test for `analyzer_init_error` in C2 that verifies the disk-write gap (or the fix to it).
