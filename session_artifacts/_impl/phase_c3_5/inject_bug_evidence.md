# Phase C3.5 — Inject-bug evidence

Per `memory/feedback_enumerate_safety_paths.md`: every new test must be proven to catch its target regression via RED→revert→GREEN cycle.

## Cycle 1 — Plugin contract (test_c3_5_multiplier_wild_plugin.py)

**Bug A**: change extract() regex from `^wild(\d+)x$` to `^never_match$`
- RED: `test_extract_parses_wild_variants` fails (no variants found)
- Revert → GREEN

**Bug B**: in emit, set `variants=[]` unconditionally
- RED: `test_emit_variants_populated` fails
- Revert → GREEN

## Cycle 2 — Isolation invariant (test_c3_5_isolation_m275_only.py)

**Bug C** (CRITICAL — guards per-machine isolation property):
- Inject: add `"multiplier_wild"` to `slot_designer/configs/machine_manifests/M14.json` analyzer_features
- RED: `test_m14_effective_version_unchanged` fails (M14 effective_version would change)
- Revert M14.json → GREEN

**Bug D** (CRITICAL — guards base_hash stability):
- Inject: touch `fresh_slotlab/analyzer/core/parser.py` (add 1 comment line)
- RED: `test_base_hash_unchanged_from_c3` fails (base_hash flips)
- Revert parser.py → GREEN

## Cycle 3 — End-to-end M275 (test_c3_5_m275_e2e.py)

**Bug E** (CRITICAL — guards 5-site registration trap):
- Inject: remove `multiplier_wild` import from one of 5 PIA registration sites
- RED: `test_m275_multiplier_wild_present` fails (silent failure → key absent from output)
- Revert → GREEN
- Validates the 5-site registration pattern critically important per coupling_audit.md §2.2

## Cycle 4 — Non-declaring machine (test_c3_5_m14_no_multiplier_wild.py)

**Bug F**: change M14.json analyzer_features to add "multiplier_wild"
- RED: `test_m14_multiplier_wild_absent` fails (key now present)
- Revert M14.json → GREEN

## Coverage summary

| Bug | Severity | Test catches | Status |
|---|---|---|---|
| A | LOW | test_extract_parses_wild_variants | ✅ RED→GREEN |
| B | LOW | test_emit_variants_populated | ✅ RED→GREEN |
| C | **CRITICAL** | test_m14_effective_version_unchanged | ✅ RED→GREEN |
| D | **CRITICAL** | test_base_hash_unchanged_from_c3 | ✅ RED→GREEN |
| E | **CRITICAL** | test_m275_multiplier_wild_present | ✅ RED→GREEN |
| F | LOW | test_m14_multiplier_wild_absent | ✅ RED→GREEN |

3 critical regression guards now protect:
- Per-machine isolation property (C, D)
- 5-site registration trap (E)
