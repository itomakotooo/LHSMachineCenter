# Ticket P2-A1 — Resolution

> **FIRST Phase 2 ticket.** Foundation files (AnalyzerFeature ABC + versioning + feature_registry) for the plugin-style analyzer architecture per `04_v5 §5.2` + `§4.1`.

## Decision: **SHIP** (after 2 rounds + main-session brief correction + dead-file cleanup)

| Round | Source | Verdict |
|---|---|---|
| R1 W1 | implementer | PASS — but followed wrong API surface (brief deviated from spec) |
| R1 W1 | tester | sufficient — 37 tests against wrong API; flagged hash algorithm spec-aligned |
| R1 W2 | verifier | PASS — code worked as written |
| R1 W2 | critic | **APPROVE-WITH-REVISIONS** — caught MAJOR brief-vs-spec API mismatch |
| Main | main session | Updated brief §3 C1 to spec-verbatim (FEATURE_ID/extract/reduce/emit ABC + 4 missing ClassVars + compute_hash classmethod) |
| R2 W1 | implementer | PASS — spec-aligned; 5 files moved/rewritten |
| R2 W1 | tester | sufficient — 23 rewritten + 20 new = 57 tests; 7/7 inject-bug |
| R2 W2 | verifier | PASS — all 17 spec elements matched verbatim; 2520/2524 full suite (4 pre-existing) |
| R2 W2 | critic | **APPROVE-WITH-REVISIONS** — R2 (delete dead feature_protocol.py) + Q3 (doc fix) |
| Main | main session | Deleted feature_protocol.py + corrected 03_tests.md manifest=None false claim |

## Process learning

**My brief was wrong**. I wrote §3 C1 from memory (`NAME/applies_to/aggregate/finalize` Protocol) instead of re-reading the spec (`FEATURE_ID/extract/reduce/emit` ABC). The implementer correctly followed the brief AND flagged the discrepancy. The critic caught it. Round 2 fixed it cleanly.

Per memory `feedback_arch_team_process.md` — arch-* is the design source of truth. When writing impl-* briefs, **re-read the spec verbatim** rather than paraphrasing from memory. This adds ~5 min per brief but prevents 30+ min round-2 cycles.

For Phase 2 remaining tickets, I'll re-read each spec section before writing the corresponding brief.

## What's solid (survived both rounds)

- `fresh_slotlab/analyzer/versioning.py:compute_effective_analyzer_version` — algorithm exactly matches `04_v5 §4.1`; 11/11 tests pass; hash determinism confirmed across 3 runs
- All subprocess import smoke tests (6 tests) — no module-level side effects
- Hash inject-bug discipline (truncate to 11 chars → tests RED → revert → GREEN)

## What changed in Round 2

| Element | Round 1 (wrong) | Round 2 (spec-verbatim) |
|---|---|---|
| File location | `fresh_slotlab/analyzer/feature_protocol.py` | `fresh_slotlab/analyzer/features/_base.py` |
| Class type | `Protocol @runtime_checkable` | `ABC + abstractmethod` |
| Name attr | `NAME: ClassVar[str]` | `FEATURE_ID: ClassVar[str]` |
| Methods | `applies_to / aggregate / finalize` | `extract / reduce / emit` |
| Missing ClassVars | (4 absent) | `SCHEMA_KEYS, REQUIRES, RTP_CONTRIBUTION, REGISTERED_FALLBACK_RULES` (all 4 added; RTP_CONTRIBUTION critical for Wave 2e gate) |
| Missing method | (absent) | `@classmethod compute_hash() -> 12-char hex of source` |
| Filtering | `feature.applies_to()` runtime predicate | `manifest.analyzer_features` declarative list |

## Main session cleanup

- **R2 (deleted)**: `fresh_slotlab/analyzer/feature_protocol.py` — round-2 critic flagged it as dead code with Wave 2b import-trap risk. Verified no remaining importers via grep; 57/57 tests still pass after deletion.
- **Q3 (doc fix)**: `03_tests.md` previously claimed `manifest=None` test exists. Critic correctly noted no such test. Doc updated to be honest about coverage gap; flagged for Phase 3 to fix.

## Open issues / out-of-scope

- `compute_base_analyzer_version()` — Wave 2b deliverable (hashes core/*.py); P2-A1 only does `compute_effective_analyzer_version`
- `compute_feature_hashes()` — Wave 2b deliverable (reads feature source files via `compute_hash()` classmethod we just added)
- `manifest=None` test coverage — Phase 3 deliverable (when real manifest loader lands)
- Q2 forward risk (compute_hash relative path): document for Wave 2b feature authors. CWD enforcement should be explicit.

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `fresh_slotlab/analyzer/__init__.py` NEW
- `fresh_slotlab/analyzer/features/__init__.py` NEW
- `fresh_slotlab/analyzer/features/_base.py` NEW (spec-verbatim AnalyzerFeature ABC)
- `fresh_slotlab/analyzer/versioning.py` NEW (compute_effective_analyzer_version per §4.1)
- `fresh_slotlab/analyzer/feature_registry.py` NEW (ALL_FEATURES + register + get_features_for_machine)
- `fresh_slotlab/analyzer/_stub_features.py` NEW (4 stubs for testing)
- `tests/backend/test_analyzer_foundation.py` NEW (57 tests)
- 7 markdown artifacts in `session_artifacts/_impl/phase2/01_foundation_files/`
- `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` (already committed earlier; ticket index)
