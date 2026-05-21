# Brief — Wave 4 Synthesizer

You walk in last. Inputs in `session_artifacts/_test/`. Your job is
the cross-machine narrative — the verifier reported per-row, you
report per-pattern.

## Inputs

- `work_plan.csv` — runner outcome per machine.
- `run_log.jsonl` — per-attempt audit.
- `02_verification.csv` — verifier's per-machine check results.
- `session_artifacts/_arch/09_architecture_as_built.md` — the
  Tier 1 / Tier 2 / Tier 3 hard-case prediction list I (main session)
  wrote based on memory + my Phase 2 implementation knowledge.

## What to produce

`session_artifacts/_test/03_final_report.md`.

### §1 Run summary

- Total reps in scope.
- Status breakdown (completed / failed / timeout / etc) with counts.
- Wall time start/end.
- Backend restarts during the run (from supervisor report).

### §2 Per-correctness-layer fleet distribution

For each layer (L1, L2, L3, L4 applicable, L4 ok, parity):
- How many machines passed / failed / skipped.
- Top 5-10 machines that failed each layer, with one-line
  `issues_summary` from the verifier CSV.

### §3 Tier prediction accuracy

Read `09_architecture_as_built.md` §3. For each Tier 1 / Tier 2 machine
I predicted as hard:
- Did it pass all applicable correctness layers? (predicted-hard but
  actually-clean → my prediction was off, machine got better OR was
  never as bad as memory suggested)
- Did it fail? Which layer? (predicted-hard and actually-hard, confirm
  the memory entry is current)
- Did the test not reach it? (sampling failed, machine has no rawdata
  even after attempt — note as "couldn't verify")

Then for any Tier 3 / unlisted machine that DID fail correctness:
- These are surprises — machines I didn't predict but the run flagged.
- Tier 1/2 list in 09_architecture_as_built.md needs adding them.

### §4 Surprise patterns

- Machines that failed at the schema layer (file written wrong /
  field missing) — these are infrastructure bugs.
- Machines whose `effective_analyzer_version` came back empty — that
  means the dual-path bug recurred OR there's a NEW dual-path issue
  hiding.
- Machines where the verifier's parity check (sum_rtp_pp ==
  summary.rtp) failed but L1 passed — that's a "two views of the
  same number disagree" signal that the aggregator parity invariant
  is broken even when the gate's own check is OK.

### §5 Recommended fixes

For each cluster of failures: what's the smallest fix that would
flip the next N machines green. Don't speculate beyond the data;
if 5 machines all failed L2 with `_unattributed_st14`, name them
+ the layer + ask: is the bonus-ST detection rule missing for
this family?

### §6 Closing — what this run did NOT cover

- Modes 2, 5, 7 not tested.
- The 26 synthetic underlying templates (M102, M116, ...) aren't
  fleet members so don't have first-class summary.json checks; only
  their representative variants got tested.
- Per-machine manifest review for the 182 `config_not_reviewed`
  machines — this run can confirm the gate ran, but the gate's
  config (anchor list, expected ST) was bootstrap default for 182,
  so L3 fails on those would mostly be "default config wrong",
  not "machine wrong".

## Constraints

- Read-only on all inputs. Don't modify the architecture doc.
- Don't classify any machine as "broken" without verifier evidence
  in `02_verification.csv` — your narrative is grounded in what the
  CSV says, not your own re-interpretation of raw summaries.
- Report under 300 words in the conversation reply. The full content
  lives in `03_final_report.md`.
