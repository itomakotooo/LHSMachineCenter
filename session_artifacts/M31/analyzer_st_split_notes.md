# M31 Analyzer ST-Split Extension Notes

Date: 2026-05-14  
Task: Extend `fresh_slotlab/player_impact_analyzer.py` with SpinType-split breakdowns  
Status: COMPLETE

---

## Summary JSON Delta

Two new fields added under `player_impact.*` (same nesting level as `payout_ids_top20`):

```
player_impact.payouts_by_spin_type: {
  "ST43_paid": [
    {
      "payout_id": str,
      "hit_count": int,
      "hit_rate_pct": float,
      "total_win": float,
      "avg_win_when_hit": float,
      "rtp_pp": float          # relative to global effective_bet_for_rtp
    }, ...
  ],
  "ST44_free": [...],
  ...
}

player_impact.reel_marginal_by_spin_type: {
  "ST43_paid": {
    "0": [{"symbol": str, "count": int, "prob_pct": float}, ...],  # col 0
    "1": [...],
    "2": [...]
  },
  "ST44_free": { ... }
}
```

Existing fields (`payout_ids_top20`, `spin_type_breakdown`, `symbols_by_column_top10`) are unchanged.

---

## MD Report Sections Added

- `## Per-pay_id by SpinType` — one markdown table per spin_type_label, columns: payout_id / hit_count / hit_rate_pct / total_win / avg_win_when_hit / rtp_pp
- `## Per-reel Marginal by SpinType` — one sub-section per spin_type_label, one markdown table per reel col, columns: symbol / count / prob_pct

---

## spin_type_label Logic (Machine-Agnostic)

Label format: `f"ST{N}_{behavior_name}"`

`behavior_name` derived from `spin_type_paid_rounds[st]` vs `spin_type_spins[st]`:
- `paid_rounds == 0` → `"free"`
- `paid_rounds == spins` → `"paid"`
- otherwise → `"mixed"`

No hardcoded SpinType values. Works on any machine without modification.

Examples across regression machines:
- M14: `ST1_paid` (single base-game type)
- M15: `ST1_paid`, `ST14_free`, `ST15_free`
- M31: `ST43_paid`, `ST44_free`
- M37: `ST1_paid`
- M279: `ST2_free`, `ST36_free`, `ST140_paid`

---

## New Accumulators in `parse_chunk_response`

`payout_id_win_by_spin_type: dict[str, dict[int, float]]`
- Parallel to existing `payout_id_by_spin_type` (hit counts)
- Populated in 3 code paths:
  1. Main `pid_to_win` attribution loop (per-round credited wins)
  2. Fallback synthesizer (residual win delta attributed to fallback pid)
  3. Trigger-session attribution (M15-style: win attributed to trigger round's ST)

`symbol_counts_by_col_by_spin_type: dict[int, dict[int, dict[str, int]]]`
- Keyed by (SpinType, col_index, symbol)
- Populated in `stop_cols` loop, same round as symbol_counts_by_col

---

## Finalize Accumulator Names

`payout_id_win_by_spin_type_total: dict[str, dict[int, float]]`
`symbol_counts_by_col_by_spin_type_total: dict[int, dict[int, dict[str, int]]]`

---

## Merge Blocks Updated

The analyzer has TWO merge blocks — both required:
1. From-cache loop (~line 4846): after `symbol_counts_by_col_by_row` merge
2. Live-sampling loop (~line 5526): same merge logic

Previous bug (caught during development): initial implementation only added merge to the live-sampling block. Re-ran `--from-cache` and observed both new fields empty (`0 cols`, `0 pids`). Fix: added identical merge to the from-cache block.

---

## Sanity Check Results (M31 mode 1, 25 chunks, 414k spins)

**payouts_by_spin_type:**
- ST43_paid (paid, 394000 spins): 12 pids, sum_rtp = 53.5231pp
- ST44_free (free, 20818 spins): 11 pids, sum_rtp = 39.0959pp
- Total: 92.62pp (matches `rtp.point_pct = 92.619%`)

**Cross-signal: sum(ST-split rtp_pp per pid) == aggregate rtp_contribution_pp**
- All top-20 pids match within 0.01pp (PASS)

**reel_marginal_by_spin_type:**
- ST43_paid: 3 cols, all prob_sum = 100.00%
- ST44_free: 3 cols (col 1 has only 4 symbols — freespin reels use fewer symbol types), all prob_sum = 100.00%

**spin_type_breakdown (cross-check):**
- ST43 (paid): 394000 spins, rtp_contribution_pp = 50.837pp (based on total_bet denominator)
- ST44 (free): 20818 spins, rtp_contribution_pp = 37.134pp

Note: `payouts_by_spin_type.rtp_pp` uses `effective_bet_for_rtp` (paid-session-only bet) as denominator, same as `payout_ids_top20.rtp_contribution_pp`. `spin_type_breakdown.rtp_contribution_pp` uses `total_bet`. The two denominators differ by the free-spin share ratio, which explains the numeric difference (53.52pp vs 50.84pp for base ST43).

---

## Regression Results

| Machine | RTP | payouts_by_spin_type labels | sum_rtp match | prob_sum=100% |
|---------|-----|-----------------------------|---------------|---------------|
| M14 | 93.49pp | ST1_paid | PASS | PASS |
| M15 | 95.66pp | ST1_paid, ST14_free, ST15_free | PASS | PASS |
| M31 | 92.62pp | ST43_paid, ST44_free | PASS | PASS |
| M37 | 95.16pp | ST1_paid | PASS | PASS |
| M279 | 93.17pp | ST2_free, ST36_free, ST140_paid | PASS | PASS |

All existing fields bit-identical to pre-extension baseline (additive-only change).

---

## Tests Added

File: `tests/backend/test_analyzer_st_split.py`
Result: 8/8 PASS

Tests:
1. `test_new_chunk_fields_present` — both new keys exist in parse_chunk_response output
2. `test_payout_id_win_by_spin_type_values` — correct win amounts per (pid, ST)
3. `test_symbol_counts_by_col_by_spin_type_structure` — col/symbol structure correct
4. `test_st_label_machine_agnostic` — label derivation uses behavior_name only, no hardcoded ST
5. `test_payout_win_by_st_totals_match_aggregate` — cross-signal: sum(ST-split) == aggregate
6. `test_reel_marginal_prob_sums_to_100` — prob_pct invariant
7. `test_existing_aggregate_fields_unchanged` — regression guard on pre-existing fields
8. `test_single_st_base_only_machine` — single-label output for machines with one ST

---

## Output Paths

- `fresh_slotlab/player_impact_analyzer.py` — modified (additive)
- `tests/backend/test_analyzer_st_split.py` — new test file
- `reports/M31/mode_1/versions/rv_st_split_v2/` — M31 regen with ST-split data

---

## Open Issues

None. Goal C (bucket distribution by ST) was decided to skip — requires rearchitecting paid-round attribution that currently ignores ST. If needed in future, would add `spin_type_bucket_spins_by_st` accumulator similar to existing `spin_type_bucket_spins`.
