# P2-A2 Critique — Manifest loader + resolvers + validation

**Critic**: impl-critic, Wave 2 (parallel to verifier)
**Date**: 2026-05-18
**Chain read**: 00_ticket.md + 02_implementation.md + 03_tests.md + manifest_loader.py + test_manifest_loader.py + 04_architecture_proposal_v5.md §5.5.1-7, §5.6, §5.11 + 07_decision_v5.md P1-P6 + all 4 fixture JSONs + manifest_schema.json

**Note**: 04_verification.md is absent (verifier runs in parallel). Critique is written against the chain that exists.

---

## Verdict: APPROVE-WITH-REVISIONS

Two implementation defects are confirmed real (C2 guard absent, C6 sentinel wrong). Three stress questions surface additional concerns the chain did not address. One question is definitively resolved in the implementer's favour. See Required Revisions below.

---

## Stress Questions (10)

---

### SQ-1 — C6 P1 vs §5.5.6: which spec wins for `resolve_layer4_applicable`?

**Question**: Patch P1 (07_decision_v5.md lines 50-57) uses `if override is not None: pattern = override` which treats JSON `null` as "no override". §5.5.6 table explicitly lists `trigger_session_pattern_override: "type_1" | "type_2" | null` as a valid override, and the example use case is "machines where session pattern differs per mode" — the `null` case is the clear-back-to-no-trigger case. The two specs produce different behaviour for `{"trigger_session_pattern_override": null}`. Which is authoritative?

**Analysis**: P1 pseudocode is labelled "verbatim" in the decision doc but it is a patch clarification written at a high level. The §5.5.6 table is the definitive field specification. The test `test_trigger_session_pattern_override` in C3 (already passing) shows the implementer's `resolve_per_mode` correctly sets `trigger_session_pattern = None` when `trigger_session_pattern_override: null` is in the per_mode block — meaning the outer function correctly folds the `null` after `resolve_per_mode` is called. The bug is only in `resolve_layer4_applicable` when called on a *pre-resolved* manifest, because the `is not None` guard there cannot distinguish "key absent" from "key=null". However: `resolve_layer4_applicable` takes a `manifest_resolved` — a post-`resolve_per_mode()` output per its docstring. In that case, `trigger_session_pattern` is already at top level (correctly set to `None` by `resolve_per_mode`), and `per_mode_overrides[mode].trigger_session_pattern_override` check is redundant and always wrong to apply again. The xfail test correctly identifies the bug in the pre-resolved path but the question of which spec wins is: **§5.5.6 wins**. The null-clear semantic is part of the field contract, not just a P1 pseudocode quirk.

**Verdict**: ✗ Not addressed — implementation has the bug, the fix is straightforward (use `_UNSET` sentinel), but neither the implementer nor the tester proposed a resolution; both deferred to impl-critic. This is a real defect.

---

### SQ-2 — C2 guard: what exception type should `resolve_inheritance` raise, and is `validate_manifest` the right enforcement point?

**Question**: The tester proposes adding a guard in `resolve_inheritance` itself (raises `ManifestValidationError` or `ValueError`). The brief §3 C2 says "Variant CANNOT override `analyzer_features` directly (only via `per_mode_overrides._add/_remove`)" — but this is the *cascade rule*, not a runtime resolver invariant. Validation rule 6 already exists to catch `console_diagnostic_complete` being set on a variant. Should the `analyzer_features` direct-override guard live in `resolve_inheritance` (hard exception) or in `validate_manifest` (soft error)?

**Analysis**: The implementer's docstring at lines 130-134 acknowledges this rule but does not enforce it. The brief's §3 C2 note says "variant CANNOT override" — the use of "CANNOT" (not "SHOULD NOT") implies a hard invariant, not a validation warning. The correct placement is `resolve_inheritance()` as a pre-merge guard (raise `ManifestValidationError` before merging). `validate_manifest` would be a second line of defence, but if the resolver silently merges it, downstream code consumes incorrect data regardless of what the validator says later. Per memory `feedback_invariant_with_fallback_hides_drift.md`: this is exactly the pattern where a fallback-swallowing merge hides structural drift.

**Verdict**: ✗ Not addressed. The guard MUST be in `resolve_inheritance` as a hard raise. A validate-only guard is insufficient.

---

### SQ-3 — `resolve_inheritance` loads parent directly via `Path(manifests_dir) / inherits_from` — does it bypass the C1 JSONDecodeError wrapping?

**Question**: `load_manifest` at lines 107-115 wraps `json.JSONDecodeError` to add the file path as context. `resolve_inheritance` at lines 167-174 open-codes the same `json.load` / `json.JSONDecodeError` re-raise pattern. But: `load_manifest` is already available in the same module. Why not call `load_manifest(parent_machine_id, manifests_dir)` instead of duplicating the open+parse logic? This is a parallel-impl violation per memory `feedback_no_parallel_panel_impl.md`.

**Analysis**: Looking at lines 161-175 of `manifest_loader.py`: `resolve_inheritance` does NOT call `load_manifest()`. It replicates the file-open + json-load + JSONDecodeError re-raise pattern. This is a textbook internal parallel implementation. The deduplicated form would be two lines: `parent_machine_id = inherits_from.removesuffix(".json")` + `parent = load_manifest(parent_machine_id, manifests_dir)`. The current form also has an inconsistency: `load_manifest` uses `Path(manifests_dir) / f"{machine_id}.json"` (always appends `.json`), whereas `resolve_inheritance` uses `Path(manifests_dir) / inherits_from` treating `inherits_from` as a filename directly (e.g. `"M15.json"` — already has `.json`). So the two paths produce equivalent results only if the caller passes `inherits_from` with `.json` already — which the spec requires. But the paths are semantically different and the duplication creates a maintenance risk.

**Verdict**: ⚠ Partial — the duplication is real; the paths happen to be equivalent given spec-compliant input. Not a runtime bug today, but a maintenance debt and a clear parallel-impl violation.

---

### SQ-4 — Does `validate_manifest` silently swallow exceptions thrown inside the validator itself?

**Question**: Per memory `feedback_no_silent_swallow.md`: the validator collects errors into a list. What happens if a rule's internal code throws an unexpected exception (e.g., `NoneType` on `manifest.get("modes_supported")` returning `None` when rules 5 iterates)? Rule 5 calls `resolve_per_mode(manifest, mode)` inside a try/except — but only `ValueError` is caught (line 619). If `resolve_per_mode` throws something unexpected (e.g., the `mode_block.items()` call on a non-dict), the exception propagates up through `validate_manifest` and the caller gets an unhandled exception rather than a clean error list.

**Analysis**: Rule 5 at lines 617-635:
```python
try:
    mode_resolved = resolve_per_mode(manifest, mode)
except ValueError as exc:
    errors.append(...)
    continue
```
This only catches `ValueError`. `resolve_per_mode` can also raise `KeyError` (if `mode_block` is not a dict — JSON allows any value for a per_mode key) and TypeError (if `mode_block.items()` is called on a non-dict). If a manifest has `"per_mode_overrides": {"1": "not_a_dict"}`, this escapes the catch, causing `validate_manifest` to throw instead of returning an error list — exactly the "swallowed error" anti-pattern but in the opposite direction (throws when it should collect). The brief says rule errors "MUST be collected not raised". Rule 5 violates this for non-ValueError exceptions.

**Verdict**: ⚠ Partial — the primary path is correct. The `ValueError`-only catch in rule 5 is a fragile boundary; a malformed manifest can escape the collect-all contract and cause an unexpected raise.

---

### SQ-5 — Rule 5 mode coverage semantics: the implementation is more conservative than the spec wording

**Question**: Rule 5 spec text (04_v5 §5.6 line 594): "for every mode in `modes_supported`, the resolved per-mode feature set must include all RTP_CONTRIBUTION=True features **that the integrity contract requires**." The implementation at lines 626-627 checks: `base_rtp = rtp_contribution_ids & set(manifest.get("analyzer_features") or [])` — i.e., only RTP_CONTRIBUTION features that are in the *base* manifest's `analyzer_features`. The spec says "that the integrity contract requires" — a more nuanced criterion that could reference a separate list. The implementer flagged this in their own risk note (02_implementation.md risk note 2): "may be overly strict vs 'that the integrity contract requires'."

**Analysis**: The implementer's interpretation is a reasonable conservative reading: if an RTP_CONTRIBUTION feature is in the base manifest, it must survive all modes. The spec wording "integrity contract requires" is ambiguous — it likely refers to the `required_attribution_anchors` list or the registry's authoritative RTP features, not a manifest-specific list. The implementation's stricter interpretation is defensible and safer than a looser one. The risk note accurately captures the ambiguity. The tester correctly notes this is "tested implicitly" with no RTP_CONTRIBUTION=True features in stubs.

**Verdict**: ⚠ Partial — the implementation is defensibly conservative but the spec is ambiguous enough that Phase 3 could reveal machines where removing an RTP_CONTRIBUTION feature for a specific mode is intentional and this rule incorrectly fires. Flag for Phase 3 fixture testing.

---

### SQ-6 — `resolve_completeness` verbatim check: does the implementation actually match §5.5.7 lines 553-573?

**Question**: The brief §3 C4 specifies "verbatim per §5.5.7 lines 553-573". The implementer claims "Implementation matches §5.5.7 verbatim: yes". Is this accurate?

**Analysis**: Comparing the spec pseudocode (04_v5 lines 552-573):
```python
_UNSET = object()
def resolve_completeness(variant_manifest, underlying_manifest) -> bool:
    underlying_complete = underlying_manifest["console_diagnostic_complete"]
    override = variant_manifest.get("console_diagnostic_complete_override", _UNSET)
    if override is _UNSET:
        return underlying_complete
    if override is False:
        return False
    raise ManifestValidationError(
        f"{variant_manifest['machine_id']}: console_diagnostic_complete_override: true "
        f"is not permitted. Variants cannot elevate completeness above their underlying."
    )
```
The implementer's code at lines 400-411 matches this exactly except the error message has an additional sentence ("Underlying {underlying_manifest['machine_id']} is the authoritative source."). The spec text is "Verbatim" for the logic; the error message is a format string with `{variant_manifest['machine_id']}` which the implementation also includes. The appended sentence does not change correctness.

**Verdict**: ✓ Adequately addressed — the algorithm is verbatim per spec. The additional error message sentence is benign.

---

### SQ-7 — Schema file (`manifest_schema.json`) is it used for validation anywhere, or is it purely documentation?

**Question**: The ticket §1 references "manifest_schema.json (referenced by §5.5.1)" and the brief says "P2-A2 ships an initial version covering all v5 fields." The Python `validate_manifest` function is the runtime enforcement. Is the JSON schema actually used anywhere in the loader or tests, or is it dead code that will drift from the Python validation logic?

**Analysis**: Grepping the codebase — `manifest_schema.json` is not imported in `manifest_loader.py`. The `validate_manifest` function does not call a JSON schema validator (`jsonschema`, `fastjsonschema`, etc.). The schema file is also not referenced in `test_manifest_loader.py`. The schema is purely documentation. This is not a runtime defect (Python validation is the source of truth), but it creates a drift risk: the Python rules can diverge from the JSON schema without any test catching it. For example: the JSON schema marks `console_diagnostic_complete_override` as `enum: [false]` (only false allowed), which matches rule 6. But rule 6 in the Python validator actually checks for `override_val is True` separately. If someone adds `enum: [false, null]` to the schema later, Python rule 6 would not catch that drift. This is the same pattern called out in memory `feedback_invariant_with_fallback_hides_drift.md` applied to schema/code parity. Phase 3 should add a test that runs JSON schema validation against each real manifest using `jsonschema` library.

**Verdict**: ⚠ Partial — not a P2-A2 bug, but a structural risk the chain did not flag. Neither the implementer (02_implementation.md) nor the tester (03_tests.md) noted that the JSON schema is never actually invoked. No test validates manifests against the schema file.

---

### SQ-8 — OI-2: `validate_manifest` called on pre- vs post-resolution manifest — rule 6 false-fire risk

**Question**: The implementer flagged OI-2: if `validate_manifest` is called on a post-`resolve_inheritance` dict, rule 6 will fire falsely because `resolve_inheritance` merges the parent's `console_diagnostic_complete` into the merged dict (a variant manifest should not have this field at the pre-resolution level, but gets it after inheritance). Is this dangerous in practice?

**Analysis**: The `resolve_inheritance` function at lines 218-222 explicitly keeps `console_diagnostic_complete` in the merged output ("we KEEP it in merged"). So a post-resolved variant manifest will always have `console_diagnostic_complete` — which triggers rule 6's `if "console_diagnostic_complete" in manifest` check (line 641). This is a real false-positive in rule 6 if callers pass a post-resolved manifest. The implementer flagged it but the proposed resolution (docstring note) is inadequate. The docstring note is not enforceable at runtime. The API needs either: (a) a parameter `is_resolved=False` so the validator can skip the check, or (b) rule 6 should check `manifest.get("inherits_from")` rather than whether `console_diagnostic_complete` is present (since after resolution the `inherits_from` is preserved and the field comes from the parent). Looking at line 641: `if "console_diagnostic_complete" in manifest:` — this check fires for any variant whose manifest was passed through `resolve_inheritance`. Phase 3 fleet-level validation will call `validate_manifest` and the natural pattern will be to pass the resolved manifest. This is a latent bug for Phase 3.

**Verdict**: ✗ Not addressed — the implementer flagged this but the proposed fix (docstring) is non-enforcement. Rule 6 will false-fire on any post-resolved variant manifest. This needs an API-level fix, not a documentation note.

---

### SQ-9 — `Patch P6` orphan override metadata: is it implemented or silently ignored?

**Question**: `07_decision_v5.md Patch P6` (lines 85-88): "If manifest has `override_set_at` / `override_set_reason` / `override_set_by` fields but no `console_diagnostic_complete_override` value: lint rule 10 emits warning 'orphan override metadata; either complete the override or remove fields'. Currently silently ignored by resolver." P6 explicitly says this should be caught. Is it caught by the validator?

**Analysis**: Rule 10 in `validate_manifest` (lines 725-739) checks:
```python
if is_variant:
    override_val = manifest.get("console_diagnostic_complete_override", _UNSET)
    if override_val is not _UNSET and override_val is False:
        # check metadata present
```
The check only runs when `console_diagnostic_complete_override` is `False`. The orphan case — metadata present but no `console_diagnostic_complete_override` — is NOT caught. The validator will return an empty error list for a manifest with `override_set_at` but no `console_diagnostic_complete_override`. P6 says this should be a warning (not an error), and it mentions `manifest_lint.py` as the enforcement point (Phase 3 §6.3.3 item 9 — out of P2-A2 scope). However, `validate_manifest` itself does not emit even a warning. The brief §3 C5 rule 10 spec: "if `console_diagnostic_complete_override: false` is present but any of ... are absent, the manifest validator emits an error." The reverse (orphan metadata) is not in the brief's rule 10 text — it appears only in P6. So P2-A2 is not strictly out of compliance with its own brief, but the chain did not notice P6 at all.

**Verdict**: ⚠ Partial — not a P2-A2 defect per the brief, but a spec commitment from P6 that the chain missed entirely. The tester's 03_tests.md does not mention P6. This will need a test in Phase 3.

---

### SQ-10 — The 4th fixture (M15$TopDollarSelector$0$) does not match the §5.11 spec example format

**Question**: The brief §6 risk notes say "P2-A2 creates M1, M15, M274 examples per §5.11." The implementer also created a 4th fixture `M15$TopDollarSelector$0$.json`. §5.11 shows two variant examples: `M273$WheelSelector$0$` and `M273$WheelSelector$42$`. The implementer created an M15-based variant instead. The §5.11 `M273$WheelSelector$0$` example has non-standard fields (`spin_type_convention_override`, `feature_tags_override`, `analyzer_features_override` — the last of which is NOT a valid field per the manifest schema). Does the fixture violate the spec?

**Analysis**:
1. The implementer's `M15$TopDollarSelector$0$.json` has only `machine_id`, `manifest_version`, `inherits_from`, `console_diagnostic_complete_override`, and the three metadata fields. This is a valid minimal variant with an override. It does NOT match the §5.11 `M273$WheelSelector$0$` shape (which includes `spin_type_convention_override`, `feature_tags_override`, `analyzer_features_override`).
2. The §5.11 `M273$WheelSelector$0$` example contains `analyzer_features_override: null` — this field does NOT exist in the spec! §5.5.6 allows `analyzer_features_add` and `analyzer_features_remove` but NOT `analyzer_features_override`. This appears to be an error in the §5.11 example itself.
3. The implementer wisely did not replicate these invalid fields. The 4th fixture correctly uses the `console_diagnostic_complete_override` + metadata form from `M273$WheelSelector$42$`.
4. However, no fixture demonstrates the `per_mode_overrides` variant path (a variant that adds per-mode overrides on top of parent's). This edge case is covered in `resolve_inheritance` (lines 206-216) but has no fixture-level test.

**Verdict**: ✓ Adequately addressed — the 4th fixture is correct and avoids the bad fields in §5.11's `M273$WheelSelector$0$` example. The chain correctly chose `M273$WheelSelector$42$` as the template. The missing variant-with-per-mode-overrides fixture is a test gap but not a defect in what was shipped.

---

## Disagreements: implementer ↔ tester ↔ verifier

**Disagreement 1 — C2 resolution path (implementer vs tester)**:
- Implementer (02_implementation.md): "Flagged for impl-critic review" — implies the guard may be in `validate_manifest` rather than `resolve_inheritance`.
- Tester (03_tests.md Gap 1): explicitly proposes the fix goes in `resolve_inheritance` as a hard raise.
- Critic resolution: tester is correct. The guard MUST be in `resolve_inheritance`. A validator-only check is insufficient because `resolve_inheritance` is the function that silently merges and produces an incorrect dict.

**Disagreement 2 — C6 spec authority (tester vs implementer)**:
- Implementer: followed P1 pseudocode (`is not None`), treats this as spec-correct.
- Tester: treats §5.5.6 table as authoritative (null is valid override), marks implementer wrong.
- Critic resolution: tester is correct. §5.5.6 table is the field contract; P1 pseudocode is an explanation-level patch. The `resolve_per_mode` function already correctly handles `null` — `resolve_layer4_applicable` must be brought into alignment.

**Disagreement 3 — OI-2 validate_manifest pre/post resolution (implementer only)**:
- Neither the tester nor verifier flagged this. The implementer self-flagged it.
- Critic resolution: this is a real latent bug, not just a docstring gap. Rule 6 false-fires on post-resolved variant manifests. Requires an API fix.

---

## Hidden assumptions

1. **`load_manifest` is always called before `resolve_inheritance`**: The API does not enforce this; a caller could construct a dict manually and pass it to `resolve_inheritance`. The function handles this correctly (dict.get works on any dict), but the `inherits_from` value must be a filename string ending in `.json` — not validated.

2. **`inherits_from` always points to a non-variant (underlying) machine**: The spec §5.5.4 says variants inherit from their underlying. But nothing in `resolve_inheritance` prevents a variant from pointing to another variant (chain inheritance). The function would follow the chain one level only (it loads the parent but does not recursively call `resolve_inheritance` on it). Chain inheritance is silently truncated.

3. **Rule 1 is fleet-level but called per-manifest**: The current implementation of rule 1 checks if the manifest's `machine_id` is in `machines_config` — but this only works correctly if a complete `machines_config` is passed. If a partial config is passed (e.g., just a subset of machines), rule 1 will false-fire for machines not in the subset. No documentation warns callers about this.

4. **`validate_manifest` skip-if-None design**: Rules 1, 2, 4, 5, 8, 9 are conditionally skipped when their inputs are `None`. A caller who forgets to pass `registry` gets partial validation with no warning. This is by design (brief §3 C5: "pass None to skip"), but the function signature does not make the consequence clear. Phase 3 fleet-level validator must pass all parameters.

5. **Post-`resolve_per_mode` manifest still contains `per_mode_overrides` block**: `resolve_per_mode` returns a deep copy with overrides applied to the top-level fields, but does NOT remove or update the `per_mode_overrides` block in the copy. So the returned dict has both the resolved top-level fields AND the original `per_mode_overrides` block. `resolve_layer4_applicable` then reads `per_mode_overrides[mode].trigger_session_pattern_override` again — potentially re-applying an override that was already folded in, or misinterpreting the state of a post-resolved manifest. The implementer acknowledged this in risk note 3 (02_implementation.md) and argues it is "benign" — but this depends on the override being idempotent, which is true for all current cases but is a hidden assumption.

---

## Edge cases not covered by the test suite

1. **Chain inheritance** (`inherits_from` pointing to another variant): `resolve_inheritance` loads the parent once. If the parent also has `inherits_from`, it is silently ignored. No test covers this.

2. **Variant with `per_mode_overrides` that conflict with parent's per_mode_overrides for the same mode and key**: The merge logic at lines 213-215 (variant's value wins key-by-key within a mode block) is tested by the existing `test_variant_inherits_*` tests but only for fields that exist only in the parent. No test creates a variant with overlapping per_mode_overrides keys.

3. **Non-dict `per_mode_overrides` value**: What if `per_mode_overrides["1"]` is `null` in JSON? The code at line 282: `mode_block = per_mode.get(str(mode))` returns `None`, then `if mode_block is None: return result` — silently treated as no override. But rule 5 also iterates over `modes_supported` and calls `resolve_per_mode` — this path is safe. The `validate_manifest` rule 5 would not catch a malformed `null` per-mode block as invalid JSON structure.

4. **`modes_supported` missing entirely**: `validate_manifest` rule 5 iterates `manifest.get("modes_supported") or []` — if absent, silently skips. Rule 7's `expected_paid_st` check would still fire. But a manifest with no `modes_supported` is structurally incomplete and should emit a validation error (not just silently skip rule 5). No test for this.

5. **Rule 9 (rawdata sanity)**: Not tested at all in the test suite (all calls use `rawdata_observed_paid_st=None`). Deferred to Phase 3, but the implementation could be wrong and no test will catch it. The gap is acknowledged in 03_tests.md but not escalated as a required fix.

6. **`_extract_machine_ids` with a hybrid machines.json** (list of dicts where some have `"machine_id"` and some have `"id"`): The implementation handles both keys via `m.get("machine_id", m.get("id", ""))` — which silently produces an empty string if neither key exists. An empty string would not match any `machine_id`. No test for this edge.

7. **Rule 11 applied per-mode**: Rule 11 checks `manifest.get("trigger_session_pattern")` at the manifest level, not per-mode. A machine with `trigger_session_pattern: null` at the base level but `trigger_session_pattern_override: "type_1"` in mode 2 + `layer4_applicable: true` would pass rule 11 (since the base-level pattern is null) but should arguably fail for mode 2. Rule 11 as currently implemented is a manifest-level check only.

---

## Required Revisions

### R1 — C2: Add `analyzer_features` direct-override guard in `resolve_inheritance` (SQ-2, Gap 1 from 03_tests.md)

**File**: `fresh_slotlab/analyzer/manifest_loader.py`, `resolve_inheritance()` function, before the merge loop (before line 187).

**Requirement**: If `manifest.get("inherits_from") is not None` and `"analyzer_features" in manifest`, raise `ManifestValidationError` with a message referencing `analyzer_features`, the machine_id, and the `per_mode_overrides._add/_remove` alternative.

**Test**: Remove the `xfail` marker from `TestC2ResolveInheritance::test_variant_cannot_override_analyzer_features_directly` and ensure it passes. Add an inject-bug test (remove the guard → test RED; restore → GREEN).

**Links to stress questions**: SQ-2 (✗), SQ-1 context, Gap 1 from 03_tests.md.

---

### R2 — C6: Fix `resolve_layer4_applicable` to use `_UNSET` sentinel (SQ-1, Gap 2 from 03_tests.md)

**File**: `fresh_slotlab/analyzer/manifest_loader.py`, `resolve_layer4_applicable()` function, lines 471-475.

**Requirement**: Replace the `if override is not None` guard with an `_UNSET` sentinel check:
```python
override = mode_block.get("trigger_session_pattern_override", _UNSET)
if override is not _UNSET:
    pattern = override
```

This allows `trigger_session_pattern_override: null` to explicitly clear the base pattern, matching §5.5.6's null-as-valid-override semantic.

**Test**: Remove the `xfail` marker from `TestC6ResolveLayer4Applicable::test_mode_override_null_returns_true` and ensure it passes. The reference implementation in `_ref_resolve_layer4_applicable` already uses `_UNSET` and serves as the ground truth.

**Links to stress questions**: SQ-1 (✗), Gap 2 from 03_tests.md.

---

### R3 — OI-2: Fix `validate_manifest` rule 6 false-fire on post-resolved variant manifests (SQ-8)

**File**: `fresh_slotlab/analyzer/manifest_loader.py`, `validate_manifest()` rule 6 block, line 641.

**Requirement**: Rule 6's `if "console_diagnostic_complete" in manifest` check fires falsely for post-`resolve_inheritance` variant manifests (which always have this field from the parent). The fix must be one of:
- (a) Rule 6 detects a post-resolved manifest via a sentinel/parameter and skips the `console_diagnostic_complete` presence check.
- (b) The `is_variant` check is supplemented by also verifying the `console_diagnostic_complete` field was NOT in the original pre-resolution manifest (impractical without original).
- (c) `resolve_inheritance` strips `console_diagnostic_complete` from the merged dict and stores it under `_underlying_console_diagnostic_complete` (internal key), which `resolve_completeness` reads. This is the cleanest but requires changing `resolve_inheritance` and `resolve_completeness` together.
- (d) Add a docstring to `validate_manifest` that makes the pre-resolution contract a documented precondition AND add a test that passes a post-resolved manifest to `validate_manifest` and asserts it emits a spurious rule 6 error (to document the known limitation rather than silently having it as a hidden trap).

Option (d) is the minimum acceptable; options (a) or (c) are preferred for correctness.

**Links to stress questions**: SQ-8 (✗), OI-2 from 02_implementation.md.

---

## Commit-Message `## Self-critique` Section

```
## Self-critique

- **C2 guard missing in `resolve_inheritance`**: Variant directly setting `analyzer_features`
  was not detected. Guard added before merge (raise ManifestValidationError). ✓ Fixed (R1).

- **C6 `resolve_layer4_applicable` uses `is not None` instead of `_UNSET` sentinel**: Cannot
  distinguish "key absent" from "key=null override". §5.5.6 table allows null to clear the
  base pattern. Sentinel fix aligns with `resolve_per_mode` which already handles null
  correctly. ✓ Fixed (R2).

- **OI-2 `validate_manifest` rule 6 false-fires on post-resolved variant manifests**:
  `resolve_inheritance` merges parent's `console_diagnostic_complete` into the merged dict.
  Rule 6 then incorrectly fires if validate is called post-resolution.
  Minimum fix: document precondition + test the known failure. ✓ Fixed (R3) or documented.

- **SQ-3 Parallel impl in `resolve_inheritance`**: Parent loading duplicates `load_manifest`
  open+parse pattern instead of calling `load_manifest`. Deferred maintenance debt; not a
  runtime bug. OPEN.

- **SQ-4 `ValueError`-only catch in rule 5**: Malformed per_mode_overrides block can escape
  the collect-all contract and throw from `validate_manifest`. OPEN for Phase 3.

- **SQ-5 Rule 5 mode coverage is more conservative than spec wording**: 'All RTP_CONTRIBUTION
  features in base manifest must survive all modes' may over-fire for intentional per-mode
  removals. Flagged for Phase 3 validation with real fixtures. OPEN.

- **SQ-7 JSON schema is never invoked**: `manifest_schema.json` is documentation only; no test
  validates against it. Phase 3 should add jsonschema validation tests. OPEN.

- **SQ-9 Patch P6 orphan metadata not implemented**: Variant with override metadata but no
  override value is silently accepted. P6 says this should warn. Out of P2-A2 scope per brief;
  deferred to Phase 3 manifest_lint.py. OPEN.

- **SQ-10 4th fixture shape vs §5.11**: §5.11 `M273$WheelSelector$0$` example contains
  `analyzer_features_override` which is not a valid field. Implementer correctly avoided
  replicating invalid fields. ✓ No action needed.

Stress questions: 10 total. 1 ✓ / 5 ⚠ / 4 ✗ (after revisions: 3 ✗ → resolved by R1/R2/R3).
```

---

## Summary

| Item | Status |
|---|---|
| C1 load + parse | ✓ Correct, loud errors, no silent fallback |
| C2 variant cannot override analyzer_features | ✗ Guard missing in resolve_inheritance (R1) |
| C3 per_mode resolution + order | ✓ Correct, inject-bug tested |
| C4 resolve_completeness verbatim | ✓ Matches spec pseudocode exactly |
| C5 validate_manifest 11 rules | ⚠ Rules 3/4/5/8/9 undertested; rule 6 has OI-2 false-fire (R3) |
| C6 resolve_layer4_applicable | ✗ `is not None` vs `_UNSET` sentinel (R2) |
| C7 subprocess import safety | ✓ Clean |
| C8 inject-bug discipline | ✓ C1/C3 full round-trip; C4/C5/C6 code-verified |
| Fixtures verbatim | ✓ M1/M15/M274 match §5.11; variant fixture correct |
| JSON schema | ⚠ Not invoked anywhere; drift risk |
| Patch P6 orphan metadata | ⚠ Not caught by validator; deferred to Phase 3 |
