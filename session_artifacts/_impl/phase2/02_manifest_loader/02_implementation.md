# P2-A2 Implementation Report — Manifest loader + resolvers + validation

## Round 2 — Verdict: pass

### Round-2 fixes applied (2026-05-18)

**Fix 1 (C2 guard — critic R1, SQ-2)**: Added pre-merge guard in `resolve_inheritance()` that raises `ManifestValidationError` before loading the parent if a variant manifest directly carries `analyzer_features` or `round_win_rules`. The tuple `_INHERITANCE_FORBIDDEN_DIRECT_OVERRIDE` covers both fields per brief §3 C2 and 04_v5 §5.5.4-5.5.5. Error message explicitly names the forbidden field and the `per_mode_overrides.<mode>.<field>_add/_remove` alternative. RAISES loudly per memory `feedback_no_silent_swallow.md`.

**Fix 2 (C6 `_UNSET` sentinel — critic R2, SQ-1)**: Replaced `mode_block.get("trigger_session_pattern_override")` + `if override is not None` in `resolve_layer4_applicable()` with `_UNSET` sentinel pattern (reusing the module-level `_UNSET = object()`). An explicit JSON `null` override now correctly clears the base pattern and returns `True` for Layer 4 applicability. Per brief §3 C6 citing §5.5.6 table (null is a valid override value; P1 pseudocode was using `is not None` which is a spec gap).

**Fix 3 (OI-2 rule 6 false-fire — critic R3, SQ-8)**: Used option (a) — added `pre_resolved: bool = True` parameter to `validate_manifest()`. Rule 6's `console_diagnostic_complete` presence check is now gated by `if pre_resolved and "console_diagnostic_complete" in manifest`. Phase 3 fleet-level callers that pass post-`resolve_inheritance()` dicts should pass `pre_resolved=False` to avoid the false-fire. The `override_val is True` check remains unconditional (correct in both paths). This is a backward-compatible API extension (default `True` preserves all existing call sites).

**xfail markers removed**:
- `TestC2ResolveInheritance::test_variant_cannot_override_analyzer_features_directly` — guard now in resolver; test passes.
- `TestC6ResolveLayer4Applicable::test_mode_override_null_returns_true` — `_UNSET` sentinel fix; test passes.
- Note: impl-implementer removed these markers per round-2 task scope ("Remove xfail strict markers on the 2 xfail tests"). Documented here per brief traceability requirement.

**OI-2 regression test class added** (`TestOI2ValidateManifestPreResolvedContract`, 4 tests):
1. `test_pre_resolved_true_no_false_fire_on_clean_variant` — clean variant pre-resolved: no rule 6 false-fire.
2. `test_post_resolved_variant_without_flag_false_fires_rule6` — documents the known limitation: post-resolved dict with default `pre_resolved=True` still false-fires (expected, per known limitation).
3. `test_post_resolved_variant_with_pre_resolved_false_no_false_fire` — fix: `pre_resolved=False` suppresses the false-fire. INJECT-BUG: remove the `if pre_resolved and` guard → RED.
4. `test_post_resolved_variant_override_true_still_fires_with_pre_resolved_false` — regression: `override_val is True` check survives even with `pre_resolved=False`. INJECT-BUG: remove the `override_val is True` check → RED.

**Pytest result (touched modules)**:
```
tests/backend/test_manifest_loader.py  96/96 passed
(90 previously passing + 2 xfail flipped to pass + 4 new OI-2 tests = 96)
```

**Pre-existing failures (not caused by these changes)**:
- `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` — present on baseline branch before this ticket. Verified by running with git stash (same failure).

**Files changed in round 2**:
| File | Change | Brief section |
|---|---|---|
| `fresh_slotlab/analyzer/manifest_loader.py` | Fix 1: C2 guard in `resolve_inheritance()` (lines 160-172) | §3 C2 + round-2 critic R1 |
| `fresh_slotlab/analyzer/manifest_loader.py` | Fix 2: `_UNSET` sentinel in `resolve_layer4_applicable()` (lines 493-496) | §3 C6 + round-2 critic R2 |
| `fresh_slotlab/analyzer/manifest_loader.py` | Fix 3: `pre_resolved` param in `validate_manifest()` + rule 6 guard | OI-2 + round-2 critic R3 |
| `tests/backend/test_manifest_loader.py` | Removed 2 `xfail(strict=True)` markers; updated docstrings | Round-2 task scope |
| `tests/backend/test_manifest_loader.py` | Added `TestOI2ValidateManifestPreResolvedContract` (4 tests) | OI-2 regression |

**Open issues (carried from round 1, not addressed in round 2 per minimal-delta discipline)**:
- SQ-3 (parallel impl in `resolve_inheritance` parent load) — maintenance debt, not runtime bug.
- SQ-4 (`ValueError`-only catch in rule 5) — Phase 3 scope.
- SQ-5 (rule 5 overly conservative vs spec wording) — Phase 3 scope.
- SQ-7 (JSON schema never invoked) — Phase 3 scope.
- SQ-9 (Patch P6 orphan metadata not caught) — Phase 3 / `manifest_lint.py` scope.

---

## Verdict: pass

---

## Files created

| File | Lines | Brief section |
|---|---|---|
| `fresh_slotlab/analyzer/manifest_loader.py` | ~540 | §3 C1-C7 |
| `slot_designer/configs/machine_manifests/manifest_schema.json` | ~220 | §2 citing 04_v5 §5.5.1-2 |
| `slot_designer/configs/machine_manifests/_fixtures/M1.json` | 23 | §2 citing 04_v5 §5.11 (verbatim) |
| `slot_designer/configs/machine_manifests/_fixtures/M15.json` | 24 | §2 citing 04_v5 §5.11 (verbatim) |
| `slot_designer/configs/machine_manifests/_fixtures/M274.json` | 32 | §2 citing 04_v5 §5.11 (verbatim) |
| `slot_designer/configs/machine_manifests/_fixtures/M15$TopDollarSelector$0$.json` | 9 | §2 citing 04_v5 §5.11 variant form |
| `session_artifacts/_impl/phase2/02_manifest_loader/02_implementation.md` | this file | — |

**Files changed (existing)**: 0 — pure additive per ticket §3 C5 minimal-delta constraint.

---

## Brief-section traceability

| Code element | Brief §| Arch spec line/section |
|---|---|---|
| `load_manifest()` | §3 C1 | 04_v5 §5.5.1 layout |
| `resolve_inheritance()` | §3 C2 | 04_v5 §5.5.4-5.5.5 |
| `resolve_per_mode()` | §3 C3 | 04_v5 §5.5.6 table + line 472 + line 474 |
| `_FORBIDDEN_PER_MODE_FIELDS` | §3 C3 | 04_v5 §5.5.6 line 472 |
| `_UNSET` sentinel | §3 C4 | 04_v5 §5.5.7 lines 553-573 |
| `resolve_completeness()` | §3 C4 | 04_v5 §5.5.7 lines 553-573 (verbatim) |
| `resolve_layer4_applicable()` | §3 C6 | 07_decision_v5.md Patch P1 lines 50-57 |
| `validate_manifest()` rules 1-11 | §3 C5 | 04_v5 §5.6 rules 1-11 |
| `ManifestValidationError` (exception) | §3 C4 | 04_v5 §5.5.7 line 569 |
| `ManifestValidationErrorItem` (alias) | §3 C5 | 04_v5 §5.6 (return list type) |
| Fixtures M1/M15/M274 | §6 risk notes | 04_v5 §5.11 verbatim |
| `manifest_schema.json` | §2 | 04_v5 §5.5.1-2 |

---

## 11 validation rules implemented per §5.6

| Rule | Status | Location in code |
|---|---|---|
| 1 — every machine in machines.json has a manifest | Implemented | `validate_manifest()` rule 1 block; skip if `machines_config=None` |
| 2 — analyzer_feature IDs in feature_registry.ALL_FEATURES | Implemented | rule 2 block; skip if `registry=None` |
| 3 — round_win_rule IDs structural check | Implemented | rule 3 block (structural; fleet-level config not passed) |
| 4 — REQUIRES dependency satisfaction | Implemented | rule 4 block; skip if `registry=None` |
| 5 — mode coverage: RTP_CONTRIBUTION features in all modes | Implemented | rule 5 block; skip if `registry=None` |
| 6 — completeness field semantics (non-variant vs variant) | Implemented | rule 6 block |
| 7 — expected_paid_st + expected_bonus_st non-empty | Implemented | rule 7 block |
| 8 — if complete=true: all RTP_CONTRIBUTION features present | Implemented | rule 8 block; skip if `registry=None` |
| 9 — rawdata sanity check (paid-ST match) | Implemented | rule 9 block; skip if `rawdata_observed_paid_st=None` |
| 10 — override=false requires metadata fields | Implemented | rule 10 block |
| 11 — trigger_session_pattern + layer4_applicable=true error | Implemented | rule 11 block |

---

## `resolve_completeness` matches §5.5.7 verbatim: yes

The pseudocode at 04_v5 §5.5.7 lines 553-573 is reproduced exactly:
- `_UNSET = object()` sentinel at module level
- `underlying_complete = underlying_manifest["console_diagnostic_complete"]`
- `override = variant_manifest.get("console_diagnostic_complete_override", _UNSET)`
- `if override is _UNSET: return underlying_complete`
- `if override is False: return False`
- `raise ManifestValidationError(...)` with verbatim message format

---

## `resolve_layer4_applicable` matches P1 verbatim: yes

Implementation reads both the base `trigger_session_pattern` AND the per-mode-block `trigger_session_pattern_override` from `per_mode_overrides[str(mode)]`, matching P1's two-step pseudocode. This handles both:
- Post-`resolve_per_mode()` dicts (override already folded in; per_mode_overrides block has no effect)
- Raw unresolved manifests (override read from per_mode_overrides block directly per P1)

---

## Subprocess import safe: yes

```
$ python -c "import fresh_slotlab.analyzer.manifest_loader; print('OK')"
OK
```

No I/O at import. All functions require explicit call to perform file reads.

---

## Pytest (touched modules)

```
tests/backend/test_analyzer_foundation.py  57/57 passed
(no existing test_manifest_loader.py — impl-tester creates this)
```

---

## Open issues: 2

### OI-1 — Rule 3 fleet-level config not wired

**Ticket §3 C5 rule 3** says "every round_win_rule ID MUST be defined in `configs/machine_round_win_rules.json` with this machine in `applies_to`". The `validate_manifest()` function does a structural check (non-empty string) but does not cross-check against `machine_round_win_rules.json` because that config path is not passed as a parameter.

**Resolution path**: Phase 3 fleet-level validation should call `validate_manifest()` with an additional `round_win_rules_config` parameter (or call a fleet-level wrapper). For per-manifest unit validation (P2-A2 scope), structural check is sufficient. Flagged for impl-critic review.

### OI-2 — Variant `console_diagnostic_complete` field detection

Rule 6 emits an error if a variant manifest carries `console_diagnostic_complete` directly. However, `resolve_inheritance()` merges the parent's `console_diagnostic_complete` into the merged dict. So if validation is called on the post-inheritance-resolved manifest, this check may falsely fire.

**Caller convention**: `validate_manifest()` should be called on the **raw** (pre-inheritance-resolved) manifest, not the resolved one, to correctly detect rule 6 violations. This is the natural call pattern (validate before resolving), but is not documented in the function signature.

**Resolution path**: Add docstring note clarifying pre-resolve vs post-resolve call expectation. Flagged for impl-critic review.

---

## Risk notes

1. **`resolve_inheritance()` merges `per_mode_overrides`** — variant's per-mode overrides are merged on top of parent's using dict update per mode key. If a variant's mode block has the same key as the parent's mode block for the same mode, the variant's value wins. This is the correct semantics (variant can narrow parent's per-mode behavior) but has not been tested with the deep-merge edge case. Flagged for impl-tester.

2. **Rule 5 mode coverage check** — checks that RTP_CONTRIBUTION features in the *base* manifest are not removed by per-mode overrides. This is conservative: if a feature was removed by per-mode override, the rule fires even if the feature is not needed for that mode's RTP. Per spec §5.6 rule 5 wording: "resolved per-mode feature set must include all RTP_CONTRIBUTION=True features that the integrity contract requires." The implementation checks all RTP_CONTRIBUTION features from the registry that are in the base manifest. This may be overly strict vs "that the integrity contract requires" — flagged for impl-critic.

3. **`resolve_layer4_applicable()` with post-resolve manifest** — when called with an already-resolved manifest (from `resolve_per_mode()`), the `trigger_session_pattern_override` in `per_mode_overrides` has already been folded into the top-level `trigger_session_pattern`. Reading `per_mode_overrides` again may double-apply if the override changes the pattern back to non-null. This is benign in the common case (override is the same or null), but edge-case: if the post-resolved manifest still has the raw `per_mode_overrides` block AND the override was `null` (reset to no-trigger-session for this mode), the double-check reads `None` from the override and does not change the pattern. Correct outcome. If override was non-null: top-level `trigger_session_pattern` already non-null (from resolve_per_mode), so `pattern` is already non-null → both paths return False correctly. No bug, but the logic is slightly redundant for the post-resolved case. Flagged for impl-critic.
