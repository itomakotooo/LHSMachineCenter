# Phase C5 — Inject-bug evidence

Per `memory/feedback_enumerate_safety_paths.md`.

## Cycle 1 — upstream_feature_breakdown plugin

**Bug A**: change emit() to write empty features list
- RED: `test_upstream_feature_breakdown_features_present` fails (M275 should have 4 features)
- Revert → GREEN

## Cycle 2 — Gap #5 payout_groups all-zeros filter (CRITICAL)

**Bug B**: remove all-zeros detection in PIA F2 inline
- RED: `test_payout_groups_top20_empty_when_all_zeros` fails (M275 returns noisy [{group:0, rtp:80.13}])
- Revert → GREEN
- Documents: gap #5 closure regression guard works

## Cycle 3 — Gap #6 chunk_spin_times recommendation (CRITICAL)

**Bug C**: change `recommended_min` formula in `collect_mechanic.emit()` to constant 1000
- RED: `test_recommended_min_matches_formula` fails (expects cycle_length * avg, got constant)
- Revert → GREEN
- Documents: gap #6 closure regression guard works

## Cycle 4 — collect_mechanic plugin

**Bug D**: change emit() to not read stash (emit empty dict)
- RED: `test_collect_mechanic_applicable` fails (M275 should be True with detected_cycle_length)
- Revert → GREEN

## Coverage summary

| Bug | Severity | Test catches | Status |
|---|---|---|---|
| A | LOW | test_upstream_feature_breakdown_features_present | ✅ RED→GREEN |
| B | **CRITICAL** | test_payout_groups_top20_empty_when_all_zeros | ✅ RED→GREEN |
| C | **CRITICAL** | test_recommended_min_matches_formula | ✅ RED→GREEN |
| D | LOW | test_collect_mechanic_applicable | ✅ RED→GREEN |

2 critical regression guards protect:
- Gap #5 closure (payout_groups all-zeros filter)
- Gap #6 closure (chunk_spin_times sizing recommendation)
