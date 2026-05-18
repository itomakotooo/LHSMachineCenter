# Ticket P2-A2 — Manifest loader + resolvers + validation

> Phase 2 / Wave 2a (last). Loader for per-machine manifests at `slot_designer/configs/machine_manifests/<M>.json` per `04_v5 §5.5`. Phase 3 will write the 421 manifests; P2-A2 just provides the loader interface used by Phase 3.

---

## §1 Ticket scope

Implement `fresh_slotlab/analyzer/manifest_loader.py` with:
- File load + JSON parse
- `inherits_from` variant cascade (§5.5.4-5.5.5; eager, by-reference)
- `per_mode_overrides` resolution (§5.5.6; `_add` / `_remove` / `_override` patterns)
- `resolve_completeness(variant, underlying) -> bool` per §5.5.7 verbatim pseudocode (lines 553-573)
- Full validation per §5.6 (11 rules; lines 588-600)
- `manifest_schema.json` (JSON Schema for static validation)

Files expected to change (new):
- `fresh_slotlab/analyzer/manifest_loader.py`
- `slot_designer/configs/machine_manifests/manifest_schema.json` (referenced by §5.5.1)
- `slot_designer/configs/machine_manifests/_fixtures/` directory with synthetic manifests for testing (Phase 3 will replace with the real 421)
- `tests/backend/test_manifest_loader.py`

**Out of scope** (Phase 3 deliverables per §6.3.3):
- Writing 421 production manifests (item 1)
- Wiring `compute_effective_analyzer_version` to consult manifest per (machine, mode) (item 3)
- Updating analyzer/backend write sites for new version (item 4)
- ALTER TABLE for `effective_analyzer_version` column (item 6)
- `scripts/manifest_lint.py` (item 9 — uses the loader but is a separate tool)
- `scripts/validate_manifests.py` CLI (item 8 — uses the loader but is CLI wrapping)

---

## §2 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.5.1-7` — manifest format + cascade + per-mode + variant override metadata (lines 369-587)
- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.6` — 11 validation rules (lines 588-600)
- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.11` — manifest examples (M1 / M15 / M274; lines 618-708)
- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.7` — runtime missing-feature error (lines 602-604)
- `session_artifacts/_arch/07_decision_v5.md P1` — per-(machine, mode) `layer4_applicable` resolution function (lines 50-58)
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — no import-time side effects
- Memory `feedback_dont_swallow_errors_in_fix.md` — validation errors must be loud, not silent

---

## §3 Contract (testable invariants)

### C1 — Load + parse single manifest
`load_manifest(machine_id: str, manifests_dir: Path) -> dict`. Reads `manifests_dir/{machine_id}.json` (or `manifests_dir/{machine_id}$<selector>$<idx>$.json` for variants per §5.5.1), returns parsed dict. Raises `FileNotFoundError` with clear message if absent. Raises `JSONDecodeError` (re-raised with context) if malformed. NO silent fallback per memory `feedback_dont_swallow_errors_in_fix.md`.

### C2 — `resolve_inheritance(manifest, manifests_dir) -> dict`
If `manifest["inherits_from"] is None`, return manifest as-is. If non-null, load the parent, deep-merge per §5.5.4-5.5.5 cascade rules:
- Variant inherits parent's `analyzer_features`, `round_win_rules`, `spin_type_convention`, `feature_tags`, `rtp_integrity_contract`, `modes_supported`
- Variant CANNOT override `analyzer_features` directly (only via `per_mode_overrides._add/_remove`)
- Variant CAN override `console_diagnostic_complete` only `true → false` (regression valve; never `false → true` — validation rule 6)

### C3 — `resolve_per_mode(manifest, mode: int) -> dict`
Apply `per_mode_overrides[str(mode)]` per §5.5.6:
- `analyzer_features_add: [...]` — append to base list
- `analyzer_features_remove: [...]` — drop from base list
- `round_win_rules_add: [...]` / `round_win_rules_remove: [...]` — same
- `bcm_target_feature_override: "..."` — replace value
- `trigger_session_pattern_override: "type_1" | "type_2" | null` — replace value
- `spin_type_convention_override: {paid, bonus}` — replace
- `feature_tags_override: [...]` — replace list entirely
- `required_attribution_anchors_override: [...]` — replace in rtp_integrity_contract
- `expected_paid_st_override` / `expected_bonus_st_override` — replace in rtp_integrity_contract

**Resolution order per §5.5.6 line 474**: `_remove` first, then `_add` (for list-type overrides).

Fields that MUST NOT have per_mode_overrides per line 472: `machine_id`, `manifest_version`, `inherits_from`, `console_diagnostic_complete`, `layer4_applicable`. Validation error if attempted.

### C4 — `resolve_completeness(variant, underlying) -> bool` per §5.5.7
Verbatim per `04_v5 §5.5.7` lines 553-573:
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

### C5 — `validate_manifest(manifest, machines_config, registry) -> list[ValidationError]` per §5.6
Implement all 11 rules per `04_v5 §5.6` lines 588-600:
1. Every machine in `configs/machines.json` MUST have a manifest file
2. Every `analyzer_feature` ID MUST correspond to a class in `feature_registry.ALL_FEATURES` (P2-A1 dependency)
3. Every `round_win_rule` ID MUST be defined in `configs/machine_round_win_rules.json` with this machine in `applies_to`
4. REQUIRES dependency satisfaction (per AnalyzerFeature.REQUIRES from P2-A1)
5. Mode coverage: per-mode resolved feature set must include all `RTP_CONTRIBUTION=True` features
6. Non-variant: `console_diagnostic_complete` boolean. Variant: absent or `console_diagnostic_complete_override: false` only. `_override: true` → error
7. `expected_paid_st` + `expected_bonus_st` non-empty; `required_attribution_anchors` validated at first run (not commit time)
8. **v3 NEW**: if `console_diagnostic_complete: true`, every `RTP_CONTRIBUTION=True` feature in registry MUST be in manifest's `analyzer_features`
9. Rawdata sanity check (skip if no rawdata; 206/421 have it) — declared `spin_type_convention.paid` matches observed paid-ST set
10. **v5 NEW**: if `console_diagnostic_complete_override: false`, all 3 metadata fields (`override_set_at`, `override_set_reason`, `override_set_by`) MUST be present + non-empty
11. **v5 NEW**: `trigger_session_pattern != null` AND `layer4_applicable: true` simultaneously is a validation error

Return a list of errors (empty list = valid). Validator does NOT raise on a single error; collects them all so operator sees the full picture.

### C6 — Per-(machine, mode) `layer4_applicable` resolution per `07_decision_v5.md P1`
Helper function per the spec verbatim:
```python
def resolve_layer4_applicable(manifest_resolved, mode: int) -> bool:
    pattern = manifest_resolved["modes"][mode].get("trigger_session_pattern")
    if pattern is None:
        return True
    return False  # any non-null trigger_session_pattern → skip Layer 4
```

### C7 — Subprocess import safety
Per memory `feedback_subprocess_import_suicide_and_module_globals.md`: `manifest_loader.py` has no import-time side effects. No I/O at import. Subprocess smoke: `python -c "import fresh_slotlab.analyzer.manifest_loader; print('OK')"` rc=0.

### C8 — Inject-bug TDD per memory `feedback_integration_test_argv.md`
For each contract (C1-C6), inject a deviation and assert tests fire:
- C1: missing manifest file → `FileNotFoundError`; malformed JSON → re-raised with context
- C2: variant tries to override `analyzer_features` directly → validation error
- C3: invalid mode key → empty per-mode result (or error per implementer's choice; document)
- C4: variant `_override: true` → ManifestValidationError
- C5 rule 11: trigger_session_pattern + layer4_applicable: true → validation error
- C6: trigger_session_pattern in any mode → layer4_applicable False for that mode

---

## §4 Out of scope (explicit, to prevent scope creep)

- Writing 421 production manifests (Phase 3 §6.3.3 item 1)
- `scripts/validate_manifests.py` CLI wrapper (Phase 3 §6.3.3 item 8)
- `scripts/manifest_lint.py` stale-override warnings (Phase 3 §6.3.3 item 9)
- Wiring `compute_effective_analyzer_version` to consult manifest (Phase 3 §6.3.3 item 3)
- Wiring `get_features_for_machine` to auto-load manifest (Phase 3 §6.3.3 item 4) — for now caller passes loaded manifest manually
- `effective_analyzer_version` DB column (Phase 3 §6.3.3 item 6)
- Backward compat with existing analyzer.main()

---

## §5 Rollback path

Single commit. `git revert <sha>` removes the new module + schema + fixtures + tests. No existing code depends on them yet (Phase 3 wires up).

---

## §6 Risk + rollback notes

**Risk class**: LOW-MEDIUM. New module + JSON schema + validation logic. Pure file-read + dict-manipulation; no subprocess; no DB; no analyzer impact.

**JSON schema bootstrap**: the schema file is referenced by §5.5.1 layout. P2-A2 ships an initial version covering all v5 fields. Phase 3 may extend if new fields appear during 421-manifest writing.

**Synthetic fixtures**: P2-A2 creates a small `_fixtures/` directory with M1, M15, M274 examples per §5.11. These are NOT production manifests — Phase 3 replaces with the real 421.

**Per memory `feedback_no_silent_swallow.md`**: validation errors must be loud (raised or returned in error list). No silent dict.get with default fallbacks that hide schema drift.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — `manifest_loader.py` + `manifest_schema.json` + `_fixtures/` per §1; 4 functions (load_manifest, resolve_inheritance, resolve_per_mode, resolve_completeness) + validate_manifest + resolve_layer4_applicable
- `impl-tester` — `tests/backend/test_manifest_loader.py` per §3 contracts C1-C8 + inject-bug discipline

### Wave 2 (parallel)
- `impl-verifier` — subprocess import smoke; all 11 validation rules tested; cascade + per_mode edge cases; pytest full suite no regression
- `impl-critic` — spec-vs-implementation cross-check (per P2-A1 lesson: verifier confirms code works, critic confirms it matches the spec); flag any deviations

Expected wall time: ~60-90 min (larger than P2-A1 due to 11 validation rules + cascade + per-mode complexity).

**P2-A1 lesson applied**: brief above was written by re-reading §5.5/§5.6 verbatim. Implementer should still cross-check pseudocode (e.g., resolve_completeness) against the actual spec at lines 553-573 before coding.
