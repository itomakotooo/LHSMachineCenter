# Phase C5 — Byte-identical / gap closure results

## Per-machine isolation invariant

| Machine | base_hash (C4 → C5) | effective_version (C4 → C5) | Status |
|---|---|---|---|
| `base_hash` | `fa440e3eb5f6` → `fa440e3eb5f6` | — | ✅ UNCHANGED (parser not touched) |
| M14 mode 1 | — | `0427b30fb92e` → `9f70eade19d5` | FLIPPED (+2 features in manifest) |
| M37 mode 1 | — | `0427b30fb92e` → `9f70eade19d5` | FLIPPED (+2 features in manifest) |
| M272 mode 1 | — | `0427b30fb92e` → `9f70eade19d5` | FLIPPED (+2 features in manifest) |
| M275 mode 1 | — | `7489a1582d6d` → `f3f2e5b58047` | FLIPPED (+2 features in manifest) |

All 253 declaring manifests had `upstream_feature_breakdown` + `collect_mechanic` added → all 253 effective_versions flip. Per coordinator decision (universal panels, prefer-complex-better).

## Gap #5 closure (payout_groups_top20 noise filter)

M275 raw: 100% rounds have `PayoutGroupId == 0`. Pre-C5: panel shows `[{group_id:0, hit_count:89090, rtp_pp:80.13}]` — noise. Post-C5: `payout_groups_top20: []` + `payout_groups_status: "all_zeros_filtered"`.

M14: no real PayoutGroupId groups either → status `"all_zeros_filtered"` or `"absent_field"`.

## Gap #6 closure (chunk_spin_times_recommendation)

M275 raw: detected_cycle_length=1000, avg_paid_spins_per_collect=5.0.

Post-C5 output (in `collect_mechanic.clamp_warning.chunk_spin_times_recommendation`):
```json
{
  "current": 5000,
  "recommended_min": 5000,   // 1000 * 5.0
  "recommended_safety": 7500, // recommended_min * 1.5
  "rationale": "BCM cycle length 1000 * 5.0 paid_spins_per_collect = 5000 min; current chunk_spin_times 5000 is borderline; recommend ≥ 7500 with 1.5x safety factor"
}
```

User clarification (2026-05-27): estimated_correction_pp=0.0 is mathematically correct; recommendation guides operator to size next sample appropriately.

## Test coverage

- 127 C5-specific tests pass (`tests/analyzer/test_c5_*.py`)
- 543 total tests/analyzer/ pass post-C5 (was 416 post-C4)
- 66/1 wave_2c (no FEATURE_SPECS update needed — implementer already added)
- 39 lookup_md5 (drift empty this round — no stash needed)

## Test debt addressed in C5 commit (renamed/updated)

- 4 C2 byte_identical tests: `_payout_groups_status` (nested `_` prefix breaks no-temp-key-leak assertion) → renamed to `payout_groups_status` (no `_`) in PIA + 3 C5 test files
- 4 C3.5 isolation tests + 1 m14_no_multiplier_wild test: stale hardcoded effective_version values `0427b30fb92e` → `9f70eade19d5` (non-M275) + `7489a1582d6d` → `f3f2e5b58047` (M275)
