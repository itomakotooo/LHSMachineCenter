# Phase C3.5 — Byte-identical / Isolation results

## Per-machine isolation invariant (THE KEY TEST)

| Machine | C3 baseline (8cda1ab) | C3.5 result | Status |
|---|---|---|---|
| `base_hash` | `fa440e3eb5f6` | `fa440e3eb5f6` | ✅ UNCHANGED |
| M14 effective_version mode 1 | `dd2ab55ef022` | `dd2ab55ef022` | ✅ UNCHANGED |
| M37 effective_version mode 1 | `dd2ab55ef022` | `dd2ab55ef022` | ✅ UNCHANGED |
| M272 effective_version mode 1 | `dd2ab55ef022` | `dd2ab55ef022` | ✅ UNCHANGED |
| **M275** effective_version mode 1 | `dd2ab55ef022` | `2ef11cd69c8d` | 🎯 **FLIPPED** (intended) |

**Result**: Textbook per-machine isolation. Only the target machine (M275) effective_version changed. 418 other machines completely unaffected.

## M275 multiplier_wild output

```
applicable: True
variants: [
  ('wild2x', 3289 total hits),
  ('wild5x', 5120 total hits),
  ('wild10x', 2682 total hits)
]
```

All 3 variants:
- Land exclusively in col 1 (verified vs raw probe)
- Cross-classified by ST (140 paid + 126 free)
- `estimated_rtp_contribution_pp: null` (v1 deferred; v2 will compute via line-win correlation)
- `estimated_rtp_method: "deferred_v2"`

## M14 (non-declaring) check

`summary["player_impact"].get("multiplier_wild")` → `None` (key absent — manifest doesn't declare).

## Test coverage

- 91 C3.5-specific tests pass (`tests/analyzer/test_c3_5_*.py`)
- 306 total tests/analyzer/ pass post-C3.5 (was 215 pre-C3.5)
- 66/1 wave_2c (incl new spec entry for multiplier_wild B-pattern)
- 39 lookup_md5 (after drift stash round 3)

## Test debt addressed

- `test_c3_base_hash_flips_for_round_level_enrichment.py::_EXPECTED_C3_BASE_HASH` updated `64409ab1b68c` → `fa440e3eb5f6` (parser comment from C3 fix-pass had shifted hash; test was stale at C3 commit time)
- `test_topo_sort.py::test_real_four_plugins_no_deps_alphabetical` renamed to `test_real_plugins_no_deps_alphabetical` + expected set extended to include `multiplier_wild` (5 plugins now)

## Drift exclusion

- `configs/machines.json` + `slot_designer/configs/machines_virtual.json` from concurrent session — stashed as `stash@{0}` round 3 (round 1 in C2, round 2 in C3, round 3 in C3.5)
