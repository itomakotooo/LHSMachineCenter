# R1 Phase 1 — Cluster E test refactor (impl-* brief)

> **Date**: 2026-05-28
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_carryforward_r1/04_architecture_proposal_v2.md` Cluster E
> **Decision doc**: `session_artifacts/_arch_carryforward_r1/07_decision.md`
> **Branch**: `claude/analyzer-unbundle-c2` (continue)
> **Commit scope**: 1 commit (E only)

---

## §1 Phase 1 purpose

Refactor 8 test files with hardcoded effective_version hex values to use dynamic `compute_effective_version_for_machine()` calls + structural differential assertions. **Test-only change**, **0 production code modified**, **0 machine invalidation**.

This eliminates the recurring "stale hex value" test debt (3 rounds during C-phase).

## §2 What this phase ships

Per W1 mapper enumeration of 8 test files (read `01_pipeline_map.md` for exact list — likely includes):
- `tests/analyzer/test_c3_5_isolation_m275_only.py`
- `tests/analyzer/test_c3_5_m14_no_multiplier_wild.py`
- `tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py`
- (5 more — implementer reads mapper to enumerate)

For each test:
1. Replace hardcoded `_NON_M275_EFFECTIVE_VERSION = "47ff60ffa3f4"` style constants with dynamic computation
2. Replace `assert ev == _PINNED_HEX` with **structural differential** assertions like:
   - "M275 differs from M14 by exactly multiplier_wild plugin hash contribution"
   - "non-M275 machines (M14, M37, M272) all share same effective_version"
   - "base_hash hex pin `fa440e3eb5f6` REMAINS (intentional pin per mapper finding)"
3. Add a shared helper module if multiple tests duplicate computation: `tests/analyzer/_version_helpers.py` with `expected_effective_version(machine_id, mode)` factored from 3 reimports per mapper duplication finding

**Important — base_hash hex pin STAYS** per W1 mapper finding. Only effective_version pins are differentialized.

## §3 What this phase MUST NOT do

- ❌ Touch any production code (`fresh_slotlab/`)
- ❌ Touch core/*.py (would flip base_hash)
- ❌ Change Cluster D / A scope
- ❌ Commit before all touched tests pass
- ❌ Skip differential assertion design — just inlining `compute_effective_version_for_machine` calls isn't enough; tests must assert **structural property**, not just current value

## §4 Acceptance criteria

1. All 8 test files updated; no hardcoded effective_version hex (except base_hash `fa440e3eb5f6`)
2. Shared helper module created (if pattern justifies — implementer decides)
3. Structural differential assertions: "M275 differs from M14 by exactly multiplier_wild contribution" type
4. All 624 tests/analyzer/ still pass
5. Bonus: future-proof — when Phase 2 (Cluster D) ships and effective_version flips again, these tests should remain GREEN automatically (the whole point of dynamic computation)

## §5 Memory feedback

- `feedback_md5_granularity_and_stamping.md` — per-mode hash semantics
- `feedback_subprocess_import_suicide_and_module_globals.md` — helper module import-safe
- `feedback_enumerate_safety_paths.md` — inject-bug protocol

## §6 Process

Standard impl-* 4-agent loop. Skip verifier (per coordinator pattern for test-only change) OR run full ceremony per user "严格走" directive.

**Coordinator decision**: full ceremony per user instruction. Spawn implementer → tester → verifier → critic.

## §7 Files implementer expected

MODIFIED:
- 8 test files in tests/analyzer/ (per W1 mapper enumeration)

NEW:
- (optional) `tests/analyzer/_version_helpers.py` if duplication justifies

NOT touched:
- Any `fresh_slotlab/` production code
- Any manifest
- Any C1 infrastructure
- web_console / auto_inspect / recovery / configs

## §8 Commit message template

```
refactor(tests): R1 Phase 1 (Cluster E) — dynamic effective_version assertions

Eliminates stale-hex-value test debt from C-phase (3 rounds of manual
hardcoded updates: C3.5, C5, C6).

8 test files updated to use compute_effective_version_for_machine() +
structural differential assertions. base_hash pin (fa440e3eb5f6) remains
per arch-mapper finding (intentional pin, not stale).

0 production code touched. 0 machine effective_version invalidation.

## Verified happy path
...

## Verified failure paths
...

## Not verified
...

## Tests added
...

## Self-critique
...
```
