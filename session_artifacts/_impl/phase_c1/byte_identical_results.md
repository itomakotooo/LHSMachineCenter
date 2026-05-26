# Phase C1 — Byte-Identical Verification Results

Date: 2026-05-25
Tester: impl-tester (Claude agent)

## Method

1. Saved C1 working tree (uncommitted changes in fresh_slotlab/ files)
2. `git stash push` the 6 modified C1 files to get pre-C1 baseline
3. Ran analyzer against M14 mode 1 cached chunks → `cache/c1_test/M14_preC1/`
4. Ran analyzer against M275 mode 1 cached chunks → `cache/c1_test/M275_preC1/`
5. `git stash pop` to restore C1 changes
6. Re-ran analyzer on same cached chunks → `cache/c1_test/M14_postC1/` and `cache/c1_test/M275_postC1/`
7. Diffed summary.json files excluding volatile fields

## Volatile fields excluded

- `report_id`, `run_id`
- `analyzer_version`, `effective_analyzer_version`, `effective_analyzer_version_error`
- `sampling.started_at`, `sampling.finished_at`, `sampling.duration_seconds`
- `guideline_comparison.rules_path`, `guideline_comparison.evaluated_at`

## Results

| Machine | Mode | Non-volatile diffs |
|---------|------|-------------------|
| M14     | 1    | **0 — IDENTICAL** |
| M275    | 1    | **0 — IDENTICAL** |

## Pre/post effective_analyzer_version (expected to flip)

| Machine | pre-C1 | post-C1 |
|---------|--------|---------|
| M14 mode 1 | `497d65f16fed` | `baf56e2f9f6e` |
| M275 mode 1 | `497d65f16fed` | `baf56e2f9f6e` |

The flip is by design (C1 modifies _base.py + 4 plugin files + adds 3 new files whose source bytes are hashed).

## Verdict

PASS — zero non-volatile diffs on both M14 and M275. C1 is byte-identical to pre-C1 baseline against the same cached chunks.
