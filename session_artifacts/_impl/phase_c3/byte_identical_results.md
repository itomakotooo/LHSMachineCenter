# Phase C3 — Byte-Identical Results

> **Date**: 2026-05-27
> **Agent**: impl-tester
> **Branch**: claude/analyzer-unbundle-c2

## Methodology

For each machine, compared the 6 legacy C2 fields in payouts_by_spin_type rows:
- `payout_id` (identity key)
- `hit_count` (int)
- `hit_rate` (float, tolerance 1e-9)
- `total_win` (float, tolerance 1e-9)
- `avg_win_when_hit` (float, tolerance 1e-9)
- `rtp_contribution_pp` (float, tolerance 1e-9)

Baseline: `cache/c2_smoke/M275_postC2/` and `cache/c2_smoke/M14_postC2/`  
Post-C3: fresh subprocess run against `rawdata/M{N}/mode_1/` using current working tree code.

## M14 mode 1

| Metric | Result |
|---|---|
| Legacy field diffs (C2 vs C3 fresh) | **0** |
| Rows in C3 output | 7 (ST1_paid, no freespin ST) |
| All rows have 4 new C3 fields | Yes |
| Rows with `shape` populated | 7/7 |
| Rows with `covered_columns` non-empty | 7/7 |
| Rows with `paylines` >= 5 entries | Yes (M14 has 5 paylines) |
| Any is_trigger_marker=True | No (M14 has no scatter trigger pid) |
| All max_match_count_observed >= 1 | Yes |
| feature_errors | {} (empty) |

**Verdict: BYTE-IDENTICAL for M14 legacy fields. C3 is purely additive.**

## M275 mode 1

| Metric | Result |
|---|---|
| Legacy field diffs (C2 vs C3 fresh) | **0** |
| Rows in C3 output | 23 (ST126_free + ST140_paid) |
| All rows have 4 new C3 fields | Yes |
| Rows with `shape` populated | 22/23 (pid 666 has shape={} by design) |
| Rows with `covered_columns` [0,1,2] | Multiple (M275 is 3×3 grid) |
| pid 666 is_trigger_marker | **True** |
| pid 27502 (jackpot) is_trigger_marker | False |
| pid 27503/27504 (jackpot) is_trigger_marker | False |
| feature_errors | {} (empty) |

**Verdict: BYTE-IDENTICAL for M275 legacy fields. C3 is purely additive.**

## base_hash Flip

| Value | Hash |
|---|---|
| C2 (commit c57c53a) | `b0ba0ce7c7e2` |
| C3 (current working tree) | `64409ab1b68c` |
| Status | **Expected per coordinator decision 2026-05-27** |

The flip is caused by parser.py adding 4 new per-round aggregation dicts
(payout_id_payline_hits / payout_id_match_count_dist / payout_id_col_set /
payout_id_has_regular_line) in the C3 block. This is architectural reality
for any round-level enrichment phase (Option A also requires a parser change).

## C3 Specific Enrichment Values Verified

| Field | M275 pid 666 | M275 pid 27502 (jackpot) | M14 pid 6 |
|---|---|---|---|
| shape | `{}` (no regular lines) | `{"3_of_a_kind": 23}` | `{"3_of_a_kind": 26014}` |
| covered_columns | `[0, 1, 2]` | `[0, 1, 2]` | `[0, 1, 2]` |
| paylines | `[{"-1": 829}]` | 5 payline entries | 5 payline entries |
| is_trigger_marker | `true` | `false` | `false` |
| max_match_count_observed | `0` | `3` | `3` |
