# Brief — Wave 3 Report-verifier

You walk in after the supervisor agent finishes. Inputs live in
`session_artifacts/_test/`. Your job is **RTP calculation
correctness**, not RTP value plausibility (per user direction
2026-05-20: "你要保证的是rtp计算过程正确，不是rtp结果在什么区间").

## Inputs

- `work_plan.csv` — per-machine status. Rows in status `completed`
  have a `summary_path` pointing at the report's `player_impact_summary.json`.
- `01_supervisor_report.md` — supervisor's summary.
- `run_log.jsonl` — per-attempt audit trail.

## Per-completed-row checks

### A. Schema integrity (file is well-formed)
- summary.json opens and is a dict.
- Required top-level keys exist: `machine`, `mode`, `rtp`, `sampling`,
  `player_impact`, `analyzer_version`, `effective_analyzer_version`,
  `rtp_integrity_check`.
- `rtp.point_pct` is a number (not None, not string).
- `sampling.total_spins` is a positive integer.

### B. New-field shape (Phase 3 + 5 contracts)
- `effective_analyzer_version` is a 12-char lowercase hex string. Empty
  string is a fail (means the dual-path bug surfaced again).
- `effective_analyzer_version_error` is None on success rows.
- `rtp_integrity_check` is a dict containing:
  `layer1_invariant_ok`, `layer2_no_fallback_buckets_ok`,
  `layer3_anchors_ok`, `layer4_applicable`, `layer4_per_st_consistency_ok`,
  `passed`, `completeness_declared`.

### C. RTP calculation correctness signals
These are the REAL test — they tell us whether the analyzer's
computation of RTP is internally consistent.

1. **L1** `layer1_invariant_ok` must be True
   (sum of payout_id_win == chunk_win invariant).
2. **L2** `layer2_no_fallback_buckets_ok` must be True
   (no `_unattributed_*` / `_other` / `_default` / `_misc` bucket;
   any of these = analyzer dropped win into an unknown bucket).
3. **L3** `layer3_anchors_ok` must be True
   (required pay_id anchors per the manifest are present with hits).
4. **L4** Either `layer4_applicable == False` (machine declared
   trigger-session pattern; structurally skipped per architecture)
   OR `layer4_per_st_consistency_ok == True` (analyzer's spin-type
   dispatch matches rawdata's SpinType count per pay_id).
5. **Cross-aggregator parity** (the user-stated invariant per memory
   `feedback_aggregator_parity_invariant.md`): if the summary has
   per-pay-id `rtp_pp` entries (typically under
   `summary.player_impact.pay_id_overview` or similar — search the
   actual file), then `abs(sum(pid.rtp_pp) - summary.rtp.point_pct)
   < 0.001`. If the field is absent, mark this check as `n/a` (not a
   fail — many machines may not export per-pid breakdown at this
   sample size).

### D. Output format
Write `session_artifacts/_test/02_verification.csv` with columns:
```
machine, mode, schema_ok, fields_present, eff_ver_format_ok,
gate_struct_ok, rtp_is_number, total_spins,
l1, l2, l3, l4_applicable, l4_ok, parity_check, rtp_value,
issues_summary
```

Where each `lN` and `parity_check` is one of:
`pass` / `fail` / `skip` / `na`.

`issues_summary` is a short human-readable list of any failed checks
("L2 fail: _unattributed_st14 present" / "parity fail: sum=86.4 vs
rtp.point_pct=85.7"). Empty if all checks pass.

**Do not classify any machine as broken** — just report what each
layer said. Synthesizer makes the cross-machine narrative.

## Self-bug-check

After writing the CSV, run an inject test (per memory
`feedback_integration_test_argv.md`): manually flip one machine's
`layer1_invariant_ok` to False in a copy of the summary, re-run your
checker on the copy, confirm `l1=fail` and `issues_summary` mentions
L1. Document the inject result in `02_verification_notes.md`.

## Constraints

- Do NOT modify any production code or any of the supervisor's
  outputs (work_plan.csv / run_log.jsonl).
- Do NOT touch the summary JSON files. Read-only.
- Report under 200 words: how many rows scanned, breakdown of pass/
  fail across the 5 checks, anything you discovered the runner
  missed.
