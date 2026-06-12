# impl-critic — Sub-pass B adversarial review
Date: 2026-06-12
Scope: fresh_slotlab/analyzer/st_extract/{__init__,_base,trigger_path}.py
       fresh_slotlab/analyzer/core/parser.py (st_extractors hook)
       fresh_slotlab/analyzer/report_engine.py (extractor resolution)
       fresh_slotlab/analyzer/versioning.py (xt: pseudo-entries)
       tests/analyzer/test_st_extract_framework.py

Base ref: coordinator diff from git (uncommitted changes on branch claude/playtype-rearch)

---

## BUG 1 — REAL-BUG: observe_round errors are silently swallowed by finalize_chunk

**File:line:** `fresh_slotlab/analyzer/st_extract/trigger_path.py:272`
  (`finalize_chunk` reset) + `fresh_slotlab/analyzer/core/parser.py` finalize block (~L2478)

**Evidence (confirmed via live execution):**

In `TriggerPathExtractor.finalize_chunk()`, line 272 clears the error list:
```python
self._obs_errors = []  # type: ignore[attr-defined]
```
The parser sequence is:
1. `observe_round` raises → parser appends to `_ext._obs_errors` (parser.py ~L2328)
2. `_ext.finalize_chunk()` is called → returns result → **clears `_obs_errors = []`**
3. Parser then reads `getattr(_ext, "_obs_errors", None)` → gets `[]` (already cleared) → no error key emitted

Running a monkeypatched `observe_round` that raises `RuntimeError` against a real `TriggerPathExtractor` instance produces `rec["st_extract"] == {"trigger_path": {}}` with NO `_extract_error_trigger_path` key. Error is gone. This directly violates `memory/feedback_no_silent_swallow.md`.

**Why the test misses it:** `test_extractor_exception_does_not_kill_parse` uses a custom `_BrokenExtractor` whose `finalize_chunk` returns `{"broken": True}` and does NOT clear `_obs_errors`. So in that test the errors are still present when the parser reads them. The real `TriggerPathExtractor` clears them. The test proves the parser's error-surfacing loop works for extractors that don't reset; it does NOT catch the real extractor's behavior.

**Verdict:** REAL-BUG. Violates an explicit memory feedback file. Every `observe_round` exception in `TriggerPathExtractor` is silently swallowed in production.

---

## BUG 2 — REAL-BUG: _begin_robot_error persists across chunks (false positive propagation)

**File:line:** `fresh_slotlab/analyzer/core/parser.py` begin_robot error path (~L1290)
  and `fresh_slotlab/analyzer/st_extract/trigger_path.py` `finalize_chunk` (no clear)

The parser sets `_ext._begin_robot_error = "..."` directly on the extractor instance when `begin_robot` raises. `finalize_chunk()` clears `_chunk_round_count`, `_chunk_win_sum`, `_chunk_win_band`, `_chunk_session_keys`, and `_obs_errors`, but **does not clear `_begin_robot_error`**.

Because the same extractor instance is reused across all chunks in a report run (report_engine resolves extractors once, passes the same list to every `parse_chunk_response` call), if any robot in chunk N raises `begin_robot`, every subsequent chunk N+1..last will also emit `_extract_error_<ID>` containing the stale error. A 20-chunk report with one bad robot in chunk 1 would stamp error keys on all 20 chunks.

Confirmed via: `ext._begin_robot_error = '...'`; `ext.finalize_chunk()` called; `_begin_robot_error` is still set afterwards.

**Verdict:** REAL-BUG. Production manifestation: if begin_robot ever fails on any robot, the noise propagates to all remaining chunks in the report. Operators seeing `_extract_error_trigger_path` in later chunks would be chasing a ghost.

---

## BUG 3 — REAL-BUG: float discriminator field silently lands in unknown bucket

**File:line:** `fresh_slotlab/analyzer/st_extract/trigger_path.py:338` `_label_from_round_field`

`str(2.0)` → `"2.0"` ≠ `"2"` (the manifest map key). Confirmed via live execution:
- `{"FieldX": 2}` (int) → `"collect_peak"` (correct)
- `{"FieldX": 2.0}` (float) → `"unknown:2.0"` (wrong)
- `{"FieldX": "2"}` (str) → `"collect_peak"` (correct)

If the upstream API returns a field value as a float (which JSON can deliver for integer-valued numeric fields depending on the serialiser — e.g. `2.0` is valid JSON for a number), every such round lands in `unknown:2.0`. The `unknown:*` bucket is a "signal bucket, never merged" per spec, so the data is not lost but it is misclassified. The test suite has no case exercising a float field value.

**Verdict:** REAL-BUG on any machine where the rawdata serialises discriminator field values as floats. For M275 the coordinator says `GameplayTriggerType` is an integer, but this is a latent trap for the next machine onboarded with a float-valued discriminator field. No test guards it.

---

## RISK 1 — RISK: win_sum uses raw WinCredits, not rule-view wins

**File:line:** `fresh_slotlab/analyzer/st_extract/trigger_path.py:279` `_get_win`

`_get_win` reads `round_dict.get("WinCredits")`, falling back to `WinAmount`. The parser computes rule-view `win_amt` via `extract_round_win(r, rules=round_win_rules)` at parser.py ~L1687, before `observe_round` is called (~L2296). The rule-view win is NOT forwarded to `round_ctx` — `round_ctx` contains `{robot_idx, round_idx, session, bet, last_paid_round, block_id}` but no `win_amt`.

Consequence: on machines with `SynthesizePayIdRule` or chunk-residual attribution, the extractor's `win_sum` will differ from the parser's `win_amt`. For M275 bonus rounds (pure `WinCredits` from API), the delta is zero in practice. But the abstraction leaks: any future machine where rule-view != WinCredits will silently produce inconsistent `win_sum` in `st_extract`.

No test guards this invariant. The F1/F2 reconciliation tests in Group F check `extracted_total == raw_total` where both sides read `WinCredits` directly — they confirm internal consistency but cannot detect rule-view drift.

**Verdict:** RISK. Low probability on current machines; medium probability on future ones. Should be documented in the extractor's docstring as a known limitation and tracked for the first machine where rule-view wins are non-trivial.

---

## RISK 2 — RISK: payout_id fallback silently misses non-zero-win trigger pids

**File:line:** `fresh_slotlab/analyzer/st_extract/trigger_path.py:397-403` `_label_from_anchor_walk`

The payout_id anchor check is:
```python
if pid_str in payout_map_str:
    win_val = payout_map_str[pid_str]
    if win_float == 0.0:
        matched_labels.append(path_label)
        continue
```

If the trigger pid carries a non-zero win (a machine whose scatter trigger simultaneously awards credits), it fails to match and falls through to `unknown:no_anchor`. The spec comment in the docstring says "A bonus-trigger payout typically awards 0 credits" but "typically" is not a hard invariant. No test covers a pid-with-win trigger.

This is not documented in the manifest schema or the error path. The operator would see unexpectedly high `unknown:no_anchor` rates with no diagnostic message explaining why.

**Verdict:** RISK. Undocumented assumption; no guard test; silent wrong labelling if violated.

---

## RISK 3 — RISK: opened_by with both payout_id AND counter keys in one path spec — undocumented behavior

**File:line:** `fresh_slotlab/analyzer/st_extract/trigger_path.py:394-420` `_label_from_anchor_walk`

When a single `opened_by` dict contains BOTH `payout_id` and `counter`+`at_peak` keys, the code processes `payout_id` first. If payout_id matches, `continue` skips to the next path — counter is never checked for the same path. So both conditions could be present but only one governs matching.

Confirmed via live test: a path with `opened_by: {payout_id: '666', counter: 'CollectCount', at_peak: 100}` where the paid round has BOTH `'666': 0` AND `CollectCount=100` matches exactly once (via payout_id). The counter clause is skipped.

This is ambiguous in the spec. The design says `opened_by` declarations are separate for each named path. Having both keys in one `opened_by` is not addressed. The behavior is deterministic but undocumented, and no test covers it.

**Verdict:** RISK. Low-probability footgun when onboarding a new machine. Needs either a schema validation reject or an explicit doc.

---

## RISK 4 — RISK: _begin_robot_error error surfacing collides with finalize_chunk error string

**File:line:** `fresh_slotlab/analyzer/core/parser.py` finalize block (~L2488)

Both `finalize_chunk` exception and `_begin_robot_error` try to append to the same `_extract_error_<ID>` string key, using string concatenation with "; " separator:
```python
existing = _st_extract_result.get(f"_extract_error_{_eid}", "")
_st_extract_result[f"_extract_error_{_eid}"] = (
    (existing + "; " if existing else "") + f"begin_robot: {_begin_err}"
)
```
If BOTH `finalize_chunk` raises AND there is a stale `_begin_robot_error`, the error string is `"finalize_chunk: ...; begin_robot: ..."`. This is a freeform string, not a structured list — it is not machine-parseable and the order depends on which block runs first. Not a crash, but a diagnostic quality issue when multiple errors co-occur.

**Verdict:** RISK. Low severity but violates the "surface diagnostic clearly" spirit of `feedback_no_silent_swallow.md`.

---

## OK-AS-DESIGNED — accepted behaviors confirmed

**Float vs int discriminator (int works):** `str(2)` → `"2"` matches map key `"2"` correctly. BUG 3 only triggers for floats.

**Block_id for paid ST declared in trigger_paths:** If a manifest erroneously declares `trigger_paths` on a paid ST, `block_id` is set to that round's own idx (is_paid update runs before observe_round), and `last_paid_round` is itself. In fallback mode, the path would likely match via payout_id (since the paid round's own PayoutIdToWinAmount is checked against its own opener). This produces semantically weird session_count inflation but no crash. **Not guarded** but the coordinator's known edge case with no manifest validation for it. OK-as-designed for now per scope.

**Malformed trigger_paths value (e.g. string):** `get_extractors_for_manifest` includes the extractor (because the key exists in the ST block), but `TriggerPathExtractor.__init__` skips non-dict `trigger_paths` values silently → `_st_declarations = {}` → extractor runs as a no-op → no crash. The `st_extract` key is present in the record but empty. Not ideal but not a crash.

**Concurrent parsing:** report_engine is single-threaded (no ThreadPoolExecutor). Same extractor instance reused serially across chunks is safe.

**Prototype not used for real parsing:** `get_extractors_for_manifest` always clones via `clone_for_manifest`. Confirmed: returned instance has a different `id()` from the registry prototype. The prototype registered with `TriggerPathExtractor({})` has `_st_declarations = {}` so would produce no output even if accidentally used.

**session_count distinctness:** `(robot_idx, block_id)` keying is correct. Two blocks from same path in same robot have different `block_id` values. Two robots with the same `block_id` would be distinguished by `robot_idx`. OK.

**Finalize double-call:** Second call returns `{}` (state already reset). Safe for the report_engine's serial chunk iteration pattern.

**Discriminator mode session_count edge case:** A block containing rounds with DIFFERENT field values (e.g., FieldX=0 followed by FieldX=2 within one block) would add the same `(robot_idx, block_id)` pair to BOTH `scatter` and `collect_peak` session_keys. Both paths get `session_count += 1` for that block. For discriminator-mode machines this is unusual (each bonus block typically has one path type), but it's a documented edge case. OK-as-designed if M275 blocks don't mix GTT values.

---

## Test gaps (Group-level)

**Group C (Parser hook):** `test_extractor_exception_does_not_kill_parse` uses `_BrokenExtractor.finalize_chunk` that does NOT clear `_obs_errors`. This makes the test pass but it does NOT catch the real `TriggerPathExtractor` behavior (BUG 1). There is no test that runs `TriggerPathExtractor.observe_round` raising and then verifies the error surfaces. **The error-surfacing test for the REAL extractor is entirely absent.**

**Group D (Semantics):** No test for `float` field values (BUG 3). No test for `payout_id` anchor with non-zero win (RISK 2). No test for multi-robot chunks (session_count across robots). No test for a robot starting with bonus rounds (no paid yet → `block_id = None` → `session_count += 0`).

**Group F (M275 real data):** `test_f5b_fallback_scatter_session_count_nonzero` explicitly skips testing `collect_peak` in fallback mode "because its anchor (CollectCount at_peak) is machine-specific and cannot be determined in a value-agnostic way." This is honest but leaves the fallback `counter`+`at_peak` path untested on real data. The gate contract (829 scatter / 80 collect_peak) from the brief is not present as a test at all — intentionally value-agnostic, which is fine, but means the actual M275 path split numbers that the coordinator verified are not locked in any test.

**Group E (Versioning):** No test verifying that editing `trigger_path.py` changes `compute_effective_version_for_machine` for a machine that declares it, but NOT for one that doesn't. This is the machine-scoped re-flagging invariant that the design calls out.

**Cross-chunk error propagation:** No test exercises a multi-chunk parse where chunk N has an error and chunks N+1+ are checked for false positive error keys (both BUG 1 and BUG 2 would be caught by such a test).

---

## 10 Stress Questions

**SQ-1 (file: trigger_path.py:272):** Delete `self._obs_errors = []` from `finalize_chunk`. Does `test_extractor_exception_does_not_kill_parse` go RED? No — because it uses `_BrokenExtractor`, not `TriggerPathExtractor`. Which test would catch it? None. Verdict: test gap + BUG 1 simultaneously confirmed.

**SQ-2 (file: parser.py ~L1290):** After chunk 1 of a real M275 report completes with a begin_robot error, how many of the remaining 19 chunks (typical 20-chunk run) report `_extract_error_trigger_path`? Answer: all 19. Is there any test that catches this? No. Verdict: BUG 2 undetected in production.

**SQ-3 (file: trigger_path.py:338):** Machine Y's upstream API serialises `GameplayTriggerType` as `2.0` (float, valid JSON). How many of machine Y's bonus rounds end up in `unknown:2.0` vs `collect_peak`? Answer: all of them. What fires in the test suite? Nothing. Verdict: BUG 3 is a latent production trap.

**SQ-4 (file: trigger_path.py:397-403):** Machine Z triggers bonus on pid `777` which always carries a 1-credit "activation" win (win != 0). Operator declares `opened_by.payout_id: "777"`. How many bonus sessions are attributed to the named path? Zero — all land in `unknown:no_anchor`. What does the report show? No obvious error, just a high unknown rate. Is it documented or tested? No. Verdict: RISK 2.

**SQ-5 (file: parser.py ~L1671 vs ~L2296):** The `is_paid` update happens at ~L1679, the `observe_round` call at ~L2296. Between those lines, the parser runs ~600 lines of other logic (payline decoding, cc tracking, chain logic). What is `_last_paid_round_for_ext` when `observe_round` is finally called? It is the CURRENT round if it's paid, or the previous paid round if it's not. This is correct. But if a paid round updates `_last_paid_round_for_ext`, and THEN the same round's `observe_round` is called, the extractor's `last_paid_round` in `round_ctx` IS that same round — the paid round sees itself as its own block opener. For fallback mode on a paid ST declared in `trigger_paths`, this means the path matching runs against the round's own payout dict. This is a logic quirk with no test.

**SQ-6 (file: __init__.py:57-89):** `ALL_EXTRACTORS` is a module-global list. `discover_extractors` is called in three places: `report_engine.py`, `versioning.py`, and multiple tests. If a subprocess imports `fresh_slotlab.analyzer.st_extract.trigger_path` before `discover_extractors` is called (e.g., a subprocess that only imports the module to get `compute_hash`), `trigger_path.py` self-registers via `register_extractor(TriggerPathExtractor({}))` at module import time. Then `discover_extractors` is called and finds the module already imported — `importlib.import_module` returns the cached module, `register_extractor` no-ops. This is safe. But the empty-manifest prototype is now in `ALL_EXTRACTORS`. Is there any path where the prototype (with `_st_declarations = {}`) gets used for real parsing? `get_extractors_for_manifest` always clones — so no. OK-as-designed.

**SQ-7 (file: parser.py ~L1269-L1277):** `_round_to_session_for_ext` maps bonus rounds to their session records. It uses `range(_s_trig + 1, _s_end)`. If a robot's first rounds are ALL bonus rounds (no paid round at all — a robot that only has bonus spins, which can happen with raw data sliced at chunk boundaries), then `compute_trigger_sessions` produces no sessions for that robot, `_round_to_session_for_ext` is empty, and every round gets `session=None` in `round_ctx`. The extractor would count `block_id=None` rounds as having no session — `if block_id is not None` guard means they are NOT counted in `session_count`. This is correct behavior for orphan bonus rounds, but it means a chunk that is entirely bonus rounds contributes zero to `session_count`. No test covers this.

**SQ-8 (file: versioning.py ~L385-L399):** `compute_effective_version_for_machine` calls `_get_extractors_for_manifest(_loaded_manifest)`. This is called with the full manifest, which triggers `clone_for_manifest` — creating a full `TriggerPathExtractor` instance just to read its `EXTRACTOR_ID`. For versioning we only need the extractor ID and hash. Creating a full instance (with full `__init__` parsing `_st_declarations`) for every call to `compute_effective_version_for_machine` is wasteful. For a fleet of 393 machines all calling this, it instantiates 393 extractor clones. Not a correctness bug but a performance RISK at fleet scale.

**SQ-9 (file: trigger_path.py:433):** The self-registration line `register_extractor(TriggerPathExtractor({}))` runs at module import time with an empty manifest. The `TriggerPathExtractor({})` instance has `_st_declarations = {}`. If a test calls `get_extractors_for_manifest` with a declaring manifest, it gets a clone — but the clone's `__init__` calls `manifest.get("spin_types")`. If `spin_types` contains ST keys that are not valid integers (e.g., `"all"`, `"default"` — unlikely but possible in a malformed manifest), `int(st_str)` raises `ValueError` which is caught and `continue`d. So malformed ST keys are silently skipped with no warning. Is this a problem? Only if someone writes a manifest with non-integer ST keys. Not tested.

**SQ-10 (file: tests/analyzer/test_st_extract_framework.py, Group E):** `test_with_trigger_paths_differs_from_without` verifies that the effective version DIFFERS between two manifests. It does NOT test that an edit to `trigger_path.py` changes the effective version only for machines declaring it and NOT for machines that don't. The carve-isolation test (Group A) tests that editing `trigger_path.py` does NOT flip `base_hash`. But there is no test that:
(a) Machine A declares `trigger_paths` → effective_version changes when `trigger_path.py` is edited.
(b) Machine B does NOT declare `trigger_paths` → effective_version is UNCHANGED when `trigger_path.py` is edited.
The fundamental per-machine re-flagging invariant from the design is not tested end-to-end.

---

## Memory feedback violations

| Feedback file | Violation |
|---|---|
| `feedback_no_silent_swallow.md` | BUG 1: `observe_round` errors accumulated in `_obs_errors` are cleared by `finalize_chunk` before the parser reads them. Errors are silently discarded in production. |
| `feedback_no_silent_swallow.md` | BUG 2: stale `_begin_robot_error` emits false positive error keys for all chunks after the first failure — not a swallow but a false signal, equally diagnostic-degrading. |

No other memory feedback files are violated. `feedback_subprocess_import_suicide_and_module_globals.md` is honored (no module-global I/O, no import-time side effects beyond `register_extractor`). `feedback_enumerate_safety_paths.md` is partially honored (inject-bug recipes exist for some paths). `feedback_integration_test_argv.md` intent is honored for Group F.

---

## Code-level bugs / risks summary

| ID | Severity | Location | Description |
|---|---|---|---|
| BUG 1 | REAL-BUG | trigger_path.py:272 + parser.py finalize | `_obs_errors` cleared by `finalize_chunk` before parser reads; observe_round errors swallowed |
| BUG 2 | REAL-BUG | parser.py:1290 + trigger_path.py (no clear) | `_begin_robot_error` not cleared by `finalize_chunk`; stale error propagates to all subsequent chunks |
| BUG 3 | REAL-BUG | trigger_path.py:338 | `str(2.0) = "2.0" != "2"`; float field values silently land in `unknown:2.0` |
| RISK 1 | RISK | trigger_path.py:279 | `_get_win` uses raw `WinCredits`, not rule-view `win_amt`; future machines with complex rules will have wrong `win_sum` |
| RISK 2 | RISK | trigger_path.py:397-403 | payout_id anchor silently fails on non-zero-win trigger pids → `unknown:no_anchor` |
| RISK 3 | RISK | trigger_path.py:394-420 | Both `payout_id` AND `counter` in same `opened_by` → undocumented precedence (payout_id wins via `continue`) |
| RISK 4 | RISK | parser.py finalize ~L2488 | Error string concatenation for co-occurring `finalize_chunk` + `_begin_robot_error` produces unparseable freeform string |

---

## Claim-vs-reality gaps (commit message vs diff)

The coordinator-cited invariant "per-extractor exceptions are caught and surfaced in the record as `_extract_error_<EXTRACTOR_ID>` entries (never silently swallowed per memory/feedback_no_silent_swallow.md)" is PARTIALLY TRUE:
- `begin_robot` exceptions: surfaced correctly (finalize_chunk does not clear `_begin_robot_error`)
- `finalize_chunk` exceptions: surfaced correctly
- `observe_round` exceptions: **NOT surfaced** — cleared by `finalize_chunk` before parser reads them (BUG 1)

The claim in the docstring at parser.py ~L516 ("Per-extractor exceptions are caught and surfaced in the record as `_extract_error_<EXTRACTOR_ID>` entries (never silently swallowed per memory/feedback_no_silent_swallow.md)") is false for `observe_round` exceptions in any extractor that resets `_obs_errors` inside `finalize_chunk`.

---

## Verdict

**FIX-FIRST**

BUG 1 is a direct violation of `feedback_no_silent_swallow.md` and undermines the core diagnostic contract of the error surfacing design. The fix is small: move `_obs_errors` collection BEFORE `finalize_chunk` resets it (collect the list before calling finalize, or have finalize return the errors alongside the data, or have finalize NOT clear `_obs_errors`). This must be fixed before commit.

BUG 2 is not data-corrupting but produces false-positive error entries across all chunks after a single begin_robot failure, making production debugging misleading. The fix is a one-line addition to `finalize_chunk`: `self._begin_robot_error = None`. Must be fixed.

BUG 3 is a latent production trap for the next machine onboarded. The fix is one line in `_label_from_round_field`: use `int(raw_val)` for numerics before stringifying, or use a normalise-to-int-if-integer-valued helper. Must be fixed before the framework is used on any new machine.

---

## Required fixes before commit/merge

1. **BUG 1 fix:** Change the error-surfacing sequence so `_obs_errors` is read BEFORE `finalize_chunk` clears it. Recommended: save `_obs_errors = list(getattr(_ext, '_obs_errors', []))` before calling `finalize_chunk`, then surface it. Add a test that triggers `observe_round` raise on a REAL `TriggerPathExtractor` instance and asserts `_extract_error_trigger_path` is present.

2. **BUG 2 fix:** Add `self._begin_robot_error = None` (and `self._obs_errors = []`) to `TriggerPathExtractor.finalize_chunk` to clear inter-chunk error state. Add a two-chunk test: chunk 1 has begin_robot error, chunk 2 does not — assert chunk 2 record has NO error key.

3. **BUG 3 fix:** In `_label_from_round_field`, normalise `raw_val` to int if it is a float equal to its integer representation before `str()` conversion: e.g. `if isinstance(raw_val, float) and raw_val == int(raw_val): raw_val = int(raw_val)`. Add a test with `{"FieldX": 2.0}` asserting label is `"collect_peak"`, not `"unknown:2.0"`.

---

## Optional improvements (non-blocking)

A. **RISK 1:** Add `win_amt` to `round_ctx` (the already-computed rule-view win from `extract_round_win`). This is a one-line addition to the `_round_ctx_for_ext` dict and future-proofs all extractors against rule-view drift. Document in `_base.py` that `round_ctx["win_amt"]` is the rule-view win.

B. **RISK 2:** Document in `trigger_path.py` `_label_from_anchor_walk` docstring that `payout_id` anchor requires `win == 0`. Consider emitting a warning log (not a crash) when a payout_id is present but non-zero, to help future debuggers.

C. **SQ-10:** Add a test that verifies the per-machine re-flagging contract: manifest WITH trigger_paths changes effective_version when trigger_path.py hash changes; manifest WITHOUT trigger_paths does NOT change when trigger_path.py hash changes.

D. **RISK 4:** Replace the freeform string concatenation for `_extract_error_<ID>` with a list of structured entries (or at minimum a newline-separated string), to make programmatic parsing of multi-error cases possible.

E. **Group F test (value-agnostic):** The fallback `collect_peak` path is currently untested on M275 real data (test F5b explicitly skips it). Now that the discriminator mode confirms `GTT=2 → collect_peak`, a round-trip test that confirms `fallback(collect_peak).session_count == discriminator(collect_peak).session_count` (within ±N% tolerance) would strengthen the cross-mode parity claim.
