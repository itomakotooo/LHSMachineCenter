# Structure-Drift Gate — Adversarial Critic Report

**Branch:** `claude/playtype-rearch`
**Files in scope (uncommitted staged changes):**
- `fresh_slotlab/analyzer/machine_spec.py`
- `fresh_slotlab/analyzer/st_extract/signature_audit.py` (new)
- `fresh_slotlab/analyzer/features/structure_drift.py` (new)
- `src/web_console/frontend/{app.js, pure.js, panel_registry.js, index.html, styles.css}`
- `tests/analyzer/test_structure_drift.py` (new)
- `tests/analyzer/test_topo_sort.py`, `test_m275_onboarding.py`, `test_l5_versioning_rewire.py`, `test_report_engine_m15_e2e.py` (modified)

---

## Stress Questions

### Q1 (PERF): observe_round per-round cost at fleet scale

**Verdict: OK — within acceptable range, with a quantified cost.**

`clone_for_manifest` precomputes `_st_signatures` and `_st_observed_only` as `frozenset[str]` at construction time (`signature_audit.py:126–138`). The frozensets are never recomputed per round. Per-round in `observe_round`: one int-keyed dict lookup (`_observed_st_counts[spin_type] += 1`), one `.get()` on `_st_signatures` (hash lookup, O(1)), then a single pass over `round_dict.items()` with two frozenset `__contains__` calls per field.

Measured exposure: M15 mode 1 = ~224 chunks × 8 robots × ~1017 rounds = **~1.82M rounds, ~17 fields each = ~30M frozenset checks**. At CPython ~50 ns per frozenset check that is roughly **1.5 s added latency per M15 report**. For a ten-machine fleet at similar scale that is **~15 s** added to a full-fleet batch. Not catastrophic for a batch pipeline running nightly; could be noticed if interactive report generation is expected to be sub-second. No benchmark or timing budget guard exists in the code or tests.

One additional cost: the `defaultdict(lambda: defaultdict(int))` nesting in `_init_chunk_state` means each new ST seen per chunk creates an inner `defaultdict(int)` lazily. For the current 2–3 STs per machine this is noise. For a machine with 30+ STs this becomes measurable.

**Risk level: LOW for current fleet size. Escalates when fleet grows past ~20 M15-scale machines or if interactive latency SLA is introduced.**

---

### Q2 (CORRECTNESS): Can a real upstream ST-logic change slip through silently?

**Cases traced:**

**(a) Upstream adds a new field → new_fields WARN?**
YES, if the field is not in `signature` and not in `observed_fields`. In `observe_round` (`signature_audit.py:203–218`): field not in `declared_fields`, not in `observed_only` → goes to `new_map`. In `emit` (`structure_drift.py:383–388`): pct > 0.0 → added to `new_fields`. WARN fires in the WARN conditions block. This path is correctly exercised by Group 2 tests.

**(b) Upstream removes an optional field → observed_fields_absent INFO (acceptable?)**
Correct by design. A field in `observed_only` dropping to 0% presence → `obs_absent` list (informational). Does NOT flip status. The `declared_sts_absent` and `per_st[st].observed_fields_absent` lists are both in the backend output and are surfaced in the frontend `sd-section sd-info` block. Operator CAN see it.

**(c) Upstream changes a field's VALUE semantics without changing presence?**
Caught by nothing in this gate (expected). The docstring (`structure_drift.py:11–18`) correctly documents this: only presence is audited, not values. Economy gates handle value semantics. No gap here per stated design.

**(d) A new ST whose rounds are < 0.1% → no FAIL, no WARN?**
This is a design gap. An undeclared ST at, say, 0.05% is listed in `undeclared_sts` but does NOT escalate status beyond "ok". The `_FAIL_UNDECLARED_ST_SHARE = 0.001` threshold is strictly greater-than (`share > 0.001`, `structure_drift.py:414`). A value of exactly 0.1% (1/1000) is NOT a FAIL, and there is no WARN tier for sub-threshold undeclared STs. If a new ST is being rolled out on 0.05% of sessions (feature flag), it is silently ok.

**Verdict: The 0.05% undeclared ST case is OK under current design (noise filter) but undocumented in tests. If the design intent is "any undeclared ST → at least WARN", the threshold or the WARN tier is missing. RISK: ACCEPTABLE-AS-KNOWN if noise-filter intent is deliberate.**

---

### Q3 (CORRECTNESS): Presence computed as key-present or value-truthy?

**Verdict: RISK (low today, medium tomorrow) — the behavior is "key-present AND value not None".**

In `observe_round` (`signature_audit.py:204–205`):
```python
for field, value in round_dict.items():
    if value is None:
        continue
```

A field present in the round dict with value `0`, `0.0`, `False`, or `""` IS counted as present (correct for `WinCredits=0` on no-win rounds). A field present with value `None` is NOT counted — it is treated as absent.

This is a design ambiguity: if upstream emits `{"FieldX": null}` to signal "this field doesn't apply this round", the extractor treats it as absent. If that field is in the `signature`, its count drops, potentially triggering WARN or FAIL. There is no comment documenting why `None` is excluded, and no test covers the `None`-value case for signature fields.

**Specific scenario:** Upstream protocol change: a previously-always-present signature field now emits `null` on 20% of rounds (e.g., `WinCredits: null` on some respin type) → field counts 80% presence → triggers WARN. Whether this is "right" or a false positive depends on protocol intent. The extractor's author decision is unverified against real data.

---

### Q4 (CORRECTNESS): Legacy chunk / manifest missing observed_fields / undeclared ST → honest status?

**Verdict: OK for all three paths.**

- **Legacy chunk (no `st_extract` key):** `extract()` checks `chunk_dict.get("st_extract")` → None → `not isinstance(None, dict)` → True → returns `{chunks_with_extract: 0, chunks_total: 1}`. After `reduce`: 0 extractor hits. `emit`: `chunks_with_extract == 0` → status `"unaudited"` with explicit reason. Never silent ok. (`structure_drift.py:301–317`). Test covered by Group 8.

- **ST with signature but no observed_fields:** `has_observed_fields = False` in extractor. In `emit`: `obs_status = "unaudited_fields"`. `has_anything = ... or obs_status == "unaudited_fields"` → `per_st_out` entry created. **BUT: the frontend renderer does NOT render `observed_fields_status` — see Q9 below for the full impact.** Backend is honest; frontend is silent.

- **Undeclared ST (in data, not in manifest):** counted in `observed_st_counts` but no per_st entry (extractor only builds per_st for STs with declared signatures). In `emit`: `st_s not in manifest_sts` → goes to `undeclared_sts` list. FAIL fires if share > 0.1%. Always visible regardless of status.

---

### Q5 (CORRECTNESS): How is an undeclared ST detected? Is a real new ST caught?

**Verdict: OK — correct detection path, two-stage mechanism.**

Stage 1: `observe_round` (`signature_audit.py:185`): `self._observed_st_counts[spin_type] += 1` fires for EVERY round including those with STs not in the manifest. This produces `observed_st_counts` with the undeclared ST's count.

Stage 2: `emit` (`structure_drift.py:331–335`): iterates `observed_st_counts`; for each `st_s not in manifest_sts` (i.e., not a JSON key in the manifest's `spin_types`), the ST is added to `undeclared_sts` with share computation.

A new ST present in the data with share > 0.1% → FAIL. Below 0.1% → visible in `undeclared_sts` list but status stays ok (see Q2d).

**The string-vs-int key matching is correct:** `finalize_chunk` uses `str(st_int)` for all keys; manifest JSON keys are naturally strings; `emit` compares `st_s` (string) against `manifest_sts` (set of manifest string keys). Type-safe.

---

### Q6 (CORRECTNESS): State-reset contract — cross-chunk bleed?

**Verdict: OK — reset is unconditional and double-enforced.**

`finalize_chunk` (`signature_audit.py:220–272`): builds result from current state, then calls `self._init_chunk_state()` (new defaultdicts created, old ones garbage-collected), then `self._obs_errors = []` and `self._begin_robot_error = None`. All three reset calls are unconditional (not inside try/except or conditional blocks). No path exits finalize_chunk without resetting.

Additionally, the parser (`core/parser.py:2488–2491`) snapshots `_obs_errors` and `_begin_robot_error` BEFORE calling `finalize_chunk` and resets them at the parser level. The extractor's own resets are documented as "idempotent guards" — defense in depth, not sole protection.

Constructed `defaultdict(lambda: defaultdict(int))` objects are fully replaced on each call to `_init_chunk_state`, so no bleed is possible even if `finalize_chunk` is called without any `observe_round` calls (empty chunk).

---

### Q7 (TESTS): Are the 36 tests value-agnostic? Does Group 10 truly lock renderer↔plugin keys?

**Verdict: MOSTLY OK — with two specific gaps.**

**Value-agnosticism:** Group 9 (real data) asserts only `status == "ok"`. No pinned RTP or field counts. Groups 1–8 use synthetic fixtures with exact counts (e.g., `declared_field_presence={"SometimesField": 50}` out of `rounds=100`) and assert exact ratios (e.g., `0.49 < pct < 0.51`). These are not "golden" values — they follow directly from the synthetic inputs, not from machine behavior. This is correct practice for pure unit tests.

**Group 10 key alignment gap:** `test_per_st_keys_match_renderer` checks (renderer per-ST keys) ⊆ (plugin per-ST keys). This is UNIDIRECTIONAL. It does NOT verify that all plugin-emitted keys that have operational meaning ARE used by the renderer. Specifically: `observed_fields_status` is emitted by the plugin (in every `per_st_out` entry) but is NOT read by the renderer (`stData.observed_fields_status` does not appear in `renderStructureDriftPanel`). The test passes because it only checks the renderer's reads against the plugin's output, not the reverse.

**Group 10 corrected-key test:** `test_renderer_does_not_read_old_bug_keys` asserts that the strings `"missing_declared_fields"` and `"new_undeclared_fields"` do not appear in the renderer function body. This is a simple substring match against the source — effective and would catch a revert.

**Gap: No test proves that `unaudited_fields` status is VISIBLE to the operator.** The inject-bug recipe IB-8 (test 8) tests the backend classification, not the frontend rendering. Deleting the `observed_fields_status` rendering from the renderer (if it existed) would not cause any test to go red.

---

### Q8 (TESTS): test_topo_sort.py change — weakened or legitimately fixed?

**Verdict: LEGITIMATE FIX for real pollution flakiness.**

The original test (`git show HEAD:tests/analyzer/test_topo_sort.py`) called `topological_sort(ALL_FEATURES)` and asserted `fids == sorted(fids)` for ALL registered features. This would FAIL whenever dep-having features (e.g., `freespin_dynamics REQUIRES payouts_by_spin_type`) were registered by other test modules collected before this one — because dep-having features are topologically ordered after their dependencies, not alphabetically relative to all features.

The new code filters `ALL_FEATURES` to only `no_dep_ids` (the six explicitly-imported dep-free features) before calling `topological_sort`. This makes the assertion pollution-resistant: regardless of which dep-having features other test files have imported, the filtered subset is always the same six features, and those six (all dep-free) sort alphabetically.

What the change DOES accomplish:
1. Verifies `structure_drift` is registered (the `len == 6` assertion).
2. Verifies the six dep-free features sort alphabetically among themselves.

What the change DROPS:
- The old membership check `set(fids) >= expected_set` is replaced by an exact-length check on the filtered subset. This is equivalent in meaning (if exactly 6 are found, they must all be present).

**No weakening. The alphabetical invariant for dep-free features is still fully checked. The change adds `structure_drift` to the tested set.**

---

### Q9 (FRONTEND): renderStructureDriftPanel — unhandled/invisible states?

**Verdict: REAL BUG (severity: medium-deferred) — `unaudited_fields` per-ST status is silently invisible.**

The renderer (`app.js:4271+`) reads these per-ST keys: `stData.signature_fields_missing`, `stData.new_fields`, `stData.observed_fields_absent`. It does NOT read `stData.observed_fields_status`.

When the backend emits `per_st[st] = {signature_fields_missing:{}, observed_fields_absent:[], new_fields:{}, observed_fields_status:"unaudited_fields"}`, all three readable dicts are empty. The renderer builds `inner = ""` and the ST block is filtered out by `.filter(Boolean)`. The `unaudited_fields` condition is invisible to the operator.

Other states:
- `status = "unaudited"` (top-level): handled — `reasonHtml` shows the reason string; `drift.reason` in JS evaluates to `undefined` (absent key) which is falsy → `reasonHtml = ""`. Works correctly via optional-chaining semantics.
- Empty `per_st` with `status = "ok"`: renderer shows `sdNoDrift` note. Correct.
- Empty `per_st` with `status = "fail"` (only undeclared STs): renders undeclared ST table + no per-ST section. Operator can see what's wrong. Correct.
- `unescaped field names`: All field names from upstream API are passed through `escapeHtml(f)` in both the `missKeys` loop and the `absentFields.map`. XSS-safe.
- `null`/`undefined` in `e.st` or `e.rounds` in `undeclared_sts`: protected by `escapeHtml(String(e.st))` and `escapeHtml(fInt(e.rounds))`. The `String()` coercion handles any type. Safe.

**Impact of the `unaudited_fields` gap:** Zero for all current machines (all 4 have `observed_fields` on every ST). First becomes visible when a new machine is onboarded with a manifest that declares `signature` but omits `observed_fields` for some ST. The backend correctly marks it; the frontend silently shows nothing for that ST. Since the backend test (Group 8) is green and the gate's top-level status is not affected, the operator sees a clean report when the situation is actually incomplete.

---

## Additional Non-Q Findings

### A1: Two dead i18n keys in pure.js (REAL, LOW SEVERITY)

`sdSource` and `sdNoUndeclaredSts` are defined in both `zh` and `en` blocks of `pure.js` but are never referenced in `app.js`.

- `sdSource`: The footer renders `escapeHtml(drift.source || "")` directly without `t()` — the source string is an English constant from the backend and is not translated. The i18n key is dead.
- `sdNoUndeclaredSts`: No UI element displays a "no undeclared STs" message — the undeclared ST section is simply hidden when `undecSts.length === 0`. The key was defined speculatively.

Both keys inflate pure.js for both languages without being used. Minor maintenance debt, not a functional bug.

### A2: `reason` key absent from normal emit output (OK, properly handled)

The schema docstring (`structure_drift.py:56`) states `"reason": str | null`. The `out` dict in normal (non-unaudited) emit does NOT include a `"reason"` key. The renderer uses `drift.reason ? ... : ""` — accessing an absent key in JavaScript returns `undefined`, which is falsy → `reasonHtml = ""`. Works correctly. However, the schema promises `null` but the backend emits the key absent (which serializes differently from `"reason": null`). A JSON-schema validator would flag this. No schema validator is in use; the frontend handles both cases.

### A3: `sig_missing` includes fields at 90%–100% exclusive (OK, operator UX concern)

`sig_missing` in `emit` captures any field with `pct < 1.0`, including those at 90%–99%. An operator looking at the frontend would see a field with 95% presence in the "Missing declared fields" section with status "ok". The section title suggests the field is absent (missing), but it just has a slight degradation that doesn't reach the WARN threshold. This is a UX confusion risk, not a correctness bug.

### A4: Memory feedback `feedback_no_silent_swallow` — honored

Extractor errors accumulate in `_obs_errors` list (not a bare `except: pass`). `finalize_chunk` exceptions are caught by the parser and surfaced as `_extract_error_<ID>` keys. `extract()` in `structure_drift.py` reads `_extract_error_signature_audit` and propagates it through `audit_errors`. `emit()` includes `audit_errors` in the output block if non-empty. The chain is complete.

### A5: Memory feedback `feedback_invariant_with_fallback_hides_drift` — honored

The plugin has no `_other` or `_unattributed` fallback bucket. Absent extractor output → explicit `"unaudited"` status with reason. Unknown status (`status not in toneMap`) in the renderer falls back to `"sd-unaudited"` CSS class and `"sdStatusUnaudited"` label (not silently hidden). The gate is designed as an alarm, not a closure mechanism. The design contract is honored.

### A6: `observed_fields_status` in `per_st_out` from `emit` docstring vs WARN conditions

The `emit()` docstring (lines 288–294) lists WARN condition `(c) observed-inventory field presence == 0 (disappeared)` and `(d) observed-inventory field presence < 90% (degraded)`. These conditions appear in the old pre-fix design. The ACTUAL code does NOT implement them as WARN escalators — observed field absence is INFORMATIONAL (`obs_absent` list only). The docstring is STALE relative to the corrected implementation. A future developer reading the docstring would expect WARN for observed-field degradation, then be confused when it does not fire. This is a documentation bug, not a code bug.

---

## Code-Level Bugs / Risks

| # | Severity | File:Line | Finding |
|---|----------|-----------|---------|
| C1 | MEDIUM-DEFERRED | `app.js:~4330`+ | `unaudited_fields` per-ST status rendered as empty block (filtered out) — invisible to operator |
| C2 | LOW | `pure.js:752,1490` | Dead i18n keys `sdSource`, `sdNoUndeclaredSts` |
| C3 | LOW | `signature_audit.py:204` | `value is None` skip semantics undocumented; upstream `null` fields count as absent even when key is present |
| C4 | LOW | `structure_drift.py:288–294` | Docstring in `emit()` lists WARN conditions for observed-field degradation that the code does NOT implement (stale from pre-fix design) |
| C5 | INFO | `structure_drift.py:444–452` | Normal emit output omits `"reason"` key; schema promises `null` but field is absent (JS-safe but schema-inconsistent) |

---

## Test-Level Gaps

| # | Severity | Test / Location | Gap |
|---|----------|----------------|-----|
| T1 | MEDIUM | `test_structure_drift.py` Group 10 | `test_per_st_keys_match_renderer` is UNIDIRECTIONAL — does not catch a plugin-emitted key that the renderer should use but doesn't. `observed_fields_status` is silently unused by renderer; no test catches this. |
| T2 | LOW | `test_structure_drift.py` Group 8 | `unaudited_fields` is tested at the BACKEND level only. No test verifies the operator CAN see it in the frontend (the rendering gap in C1). |
| T3 | LOW | `test_structure_drift.py` Group 3 | No test for a signature field with `value=None` — is it counted as present or absent? The extractor skips `None`, so it counts as absent → potential WARN/FAIL. Undocumented and untested. |
| T4 | INFO | `test_structure_drift.py` | No boundary test for undeclared ST at exactly 0.1% share (1/1000). Current tests use 1/1001 (below) and 10/1000 (above). The threshold uses `>` (strictly greater), so 0.1% exact is OK, but this is undocumented in tests. |
| T5 | INFO | Group 9 | `test_m43_mode7_ok` and `test_m43_mode1_ok` are separate tests for the same machine (different modes). Correct isolation, but only one chunk (`chunk_0002.json`) is tested per mode, not the full mode directory. No risk since Group 9 is value-agnostic. |

---

## Claim-vs-Reality Gaps (commit claims vs diff)

| Claim | Reality |
|-------|---------|
| "base_hash c5d2199142c3 unchanged" | VERIFIED: `signature_audit.py`, `structure_drift.py`, and `machine_spec.py` are all excluded from `_CLOSURE_FILES`. `st_extract/__init__.py` (in closure) is unmodified. Base hash is unchanged. |
| "auto-attaches to every machine because all manifests declare signature" | VERIFIED: All 4 manifest JSON files (`M15`, `M43`, `M275`, `M279`) declare `"signature"` on every ST. `DECLARED_IN_KEY = "signature"` triggers on `any ST block` having the key. Confirmed via manifest inspection. |
| "All 4 machines now emit status 'ok'" | Plausible but not independently verified here (no test run). Group 9 tests cover this claim and they are described as green. The logic path for ok is correctly traced. |
| "36 new tests green" | The 36 tests cover Groups 1–11. Logic is sound for Groups 1–8 (unit). Group 9 (real data) and Group 10 (frontend alignment) are structurally correct but the Group 10 unidirectionality gap (T1) is real. |
| "goldens re-baselined" | `test_report_engine_m15_e2e.py` adds `"structure_drift"` to `_EXPECTED_TOP_KEYS`. `test_m275_onboarding.py` adds `"structure_drift"` to expected analyses and top keys. Both are additive, not destructive. |

---

## Verdict: APPROVE-WITH-FIXES

The core classification logic (FAIL/WARN/OK/unaudited) is correct and well-tested. The false-positive fix (no WARN for observed-field low presence) is correctly implemented and protected by IB-6 and IB-7 inject-bug regression tests. The base_hash isolation claim is verified. The extractor state-reset contract is honored. The topo_sort change is a legitimate pollution fix, not a weakening.

### Required Fixes Before Commit/Merge

1. **(C1 / T1 / T2) — `unaudited_fields` invisible in renderer:** Either (a) add rendering for `stData.observed_fields_status === "unaudited_fields"` in `renderStructureDriftPanel` as a warning note inside the ST block, OR (b) explicitly document in a comment that the current 4-machine fleet has no STs with this status and accept it as a known deferred gap with a `// TODO` marker. Without (a) or explicit (b), the feedback_no_silent_swallow contract is violated at the UI layer: the backend surfaces `"unaudited_fields"` but the operator cannot see it. **If deferred, add a test or comment that explicitly marks the gap.**

2. **(C4) — stale `emit()` docstring:** Remove or correct the WARN conditions `(c)` and `(d)` in the `emit()` docstring (`structure_drift.py:288–294`) that describe observed-field WARN triggers the code does not implement. The docstring contradicts the corrected design.

### Optional Improvements (non-blocking)

1. **(A1) — Dead i18n keys:** Remove `sdSource` and `sdNoUndeclaredSts` from both `zh` and `en` blocks in `pure.js`, or wire `sdSource` into the footer `t()` call.

2. **(T3) — `value=None` test:** Add a test case where a signature field has `value=None` in the round dict and assert the extractor treats it as absent (with a comment explaining this is the intentional behavior for null-value protocol transitions).

3. **(A2 / C5) — `reason` key:** Make the normal (non-unaudited) emit include `"reason": null` explicitly so the schema matches the docstring promise.

4. **(Q2d) — Sub-threshold undeclared ST documentation:** Add a comment in `emit()` near the FAIL check explaining the 0.1% noise filter and that sub-threshold undeclared STs are surfaced in `undeclared_sts` list without escalating status.

5. **(Q1) — Performance note:** Add a comment in `observe_round` noting the per-round cost scale and the `_MAX_NEW_TRACKED = 50` guard as the memory bounding mechanism. Consider a future optimization path (e.g., pre-built `all_known` set as a class attribute rather than computed in observe_round).
