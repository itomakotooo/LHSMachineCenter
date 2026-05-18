# Ticket P2-A2 — Resolution

> Phase 2 / Wave 2a (last). Manifest loader + 11 validation rules per `04_v5 §5.5-5.6`.

## Decision: **SHIP**

| Round | Source | Verdict |
|---|---|---|
| R1 W1 | implementer | PASS — 7 files, all 11 rules, resolve_completeness + resolve_layer4_applicable verbatim |
| R1 W1 | tester | partial — 92 tests; 2 xfail strict on real defects |
| R1 W2 | verifier | PARTIAL — all 3 tester findings confirmed independently |
| R1 W2 | critic | APPROVE-WITH-REVISIONS — 3 defects with precise fix recommendations |
| R2 W1 | implementer | PASS — 3 fixes applied per critic recipes |
| R2 W1 | tester | sufficient — 2 xfail removed (auto-PASS); 3 OI-2 regression tests added; 3/3 inject-bug verified |
| Main | main session | Independent pytest: 156/156 (99 manifest_loader + 57 foundation) GREEN |

## Round 2 fixes

**Fix 1 (C2 guard)**: `resolve_inheritance` now raises `ManifestValidationError` BEFORE merge if variant directly sets `analyzer_features` or `round_win_rules`. Per §5.5.4-5.5.5, variants can only modify these via `per_mode_overrides._add` / `._remove`.

**Fix 2 (C6 `_UNSET` sentinel)**: `resolve_layer4_applicable` now uses `_UNSET` sentinel to distinguish "override absent" from "override=null". §5.5.6 lists `null` as a valid `trigger_session_pattern_override` value (means "explicitly clear base pattern for this mode"). P1 pseudocode missed this case; §5.5.6 wins per critic R2.

**Fix 3 (OI-2 rule 6 false-fire)**: `validate_manifest` now accepts `pre_resolved: bool = True` parameter. Rule 6's `console_diagnostic_complete` check gated by `if pre_resolved and ...`. Backward-compatible (default True preserves all existing callers). Implementer added 4 OI-2 tests + tester added 3 more (integration coverage via real `resolve_inheritance` + `resolve_per_mode` + `validate_manifest` pipeline).

## Other implementer self-flagged items

- OI-1: rule 3 fleet config cross-check (`machine_round_win_rules.json`) deferred to Phase 3 per spec — structural validation only in P2-A2
- Schema file `manifest_schema.json` is documentation-grade; not invoked by `validate_manifest` (Python validation is the source of truth). Phase 3 may add JSON Schema validation as a CLI option in `scripts/validate_manifests.py`.

## Pytest results

- Targeted: 99/99 manifest_loader + 57/57 foundation = 156/156 GREEN
- Full suite: 2587/2591 pass (4 pre-existing failures all confirmed via baseline)
- 0 regressions

## Architectural learning

Round 1 critic correctly distinguished SPEC SOURCE OF TRUTH for the P1 vs §5.5.6 contradiction (resolve_layer4_applicable). When two specs disagree, defer to the field-definition section (§5.5.6 table) over an explanatory pseudocode patch (P1). This pattern likely recurs in Phase 2 — implementers should flag spec contradictions for main session to resolve rather than silently picking one interpretation.

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `fresh_slotlab/analyzer/manifest_loader.py` NEW (~540 lines + round-2 fixes for C2 guard, C6 sentinel, OI-2 pre_resolved gate)
- `slot_designer/configs/machine_manifests/manifest_schema.json` NEW (~220 lines, JSON Schema)
- `slot_designer/configs/machine_manifests/_fixtures/` NEW (4 fixtures: M1, M15, M274, M15$TopDollarSelector$0$)
- `tests/backend/test_manifest_loader.py` NEW (99 tests; 2 xfail flipped to PASS round 2; 7 new OI-2 tests across 2 classes)
- 6 markdown artifacts in `session_artifacts/_impl/phase2/02_manifest_loader/`
