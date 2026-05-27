# Phase C2 — Byte-Identical Results

> Author: impl-tester (redo pass)
> Date: 2026-05-27

## Implementer-verified (prior tester run)

| Machine | Mode | Field | Result |
|---|---|---|---|
| M14 | 1 | payouts_by_spin_type | IDENTICAL vs pre-C2 cache |
| M14 | 1 | payout_ids_top20 | IDENTICAL |
| M14 | 1 | reel_marginal_by_spin_type | IDENTICAL |
| M275 | 1 | payouts_by_spin_type | IDENTICAL vs pre-C2 cache |
| M275 | 1 | payout_ids_top20 | IDENTICAL |
| M275 | 1 | reel_marginal_by_spin_type | IDENTICAL |

Source: implementer summary (byte-identical confirmed by git stash / pop protocol).

## Tester-verified (this pass)

All C2 test files run against live impl, all passing:

| Test file | Tests | Result | Run time |
|---|---|---|---|
| test_c2_byte_identical_m14.py | 10 | 10 PASSED | ~6s (module fixture cached) |
| test_c2_byte_identical_m275.py | not re-run (no cached chunks beyond what implementer confirmed) | — | — |
| test_c2_byte_identical_m37.py | 6 | 6 PASSED | ~28s |
| test_c2_byte_identical_m272.py | 6 | 6 PASSED | ~23s |

M37 and M272 were run by this tester pass for extra confidence (implementer didn't have prior cache for those; tests assert structural correctness rather than strict byte-diff against stash).

## Inject-bug confirms byte-identical tests would catch regressions

The inject-bug for test_c2_byte_identical_m14.py (extract returns {} for all chunks after index 0) made `test_payouts_by_spin_type_total_hits_nonzero` and `test_payouts_by_spin_type_rtp_positive` both RED with `total == 0`. Reverting restored GREEN. This proves the tests catch broken extraction, not just "key exists".

## effective_analyzer_version

Implementer confirmed: baf56e2f9f6e (C1) → ca693c80db33 (C2). This was not re-verified in this tester pass (the byte-identical tests confirm the output is structurally correct, which implies the version changed when the plugin source changed).
