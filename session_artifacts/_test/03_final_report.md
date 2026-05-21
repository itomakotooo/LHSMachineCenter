# Wave 4 — Fleet Smoke Test, Final Report

Synthesizer pass over the runner CSVs, audit log, verifier CSV, and the
"as-built" architecture doc. Per-row data lives in `02_verification.csv`;
this report is the cross-machine narrative.

---

## §1 Run summary

- **Scope**: 255 (machine, mode=1) work items — 393 fleet members minus
  variants/templates that copied from a primary; 203 copy-from-main +
  52 fresh-sample.
- **Outcome**: 254 completed / 1 failed.
  - Failed: **M276** — upstream sampling produced 0 spins after
    `max_chunks_reached`. Not a manifest gap (M276.json exists);
    looks like an upstream-rawdata issue specific to this machine.
- **Wall time**: 2026-05-20 06:16:04Z → 15:48:17Z, **~9h32m**.
- **Reliability events** (from `run_log.jsonl`):
  - 4 supervisor interventions (3 `timeout→completed` reclassifications
    + 1 orphan-completion fix). No backend restarts logged.
  - 14 `retry_reset` events for 6 trigger-session machines (M102, M116,
    M117, M12, M123, M132) — all eventually completed after upstream
    rate-limit backoff. Consistent with the known per-IP throttle
    behavior; not a test-infra failure.

---

## §2 Per-correctness-layer fleet distribution

Layer counts (denominator 254 reports):

| Layer | Pass | Fail | Skip | Notes |
|---|---|---|---|---|
| L1 (algorithm consistency) | 254 | 0 | 0 | Arithmetic is always internally consistent. |
| L2 (no `_unattributed_*`) | 195 | **59** | 0 | **Biggest signal.** |
| L3 (anchor coverage) | 254 | 0 | 0 | Weak signal — 182 manifests still use bootstrap-default empty anchor lists. |
| L4 (rawdata cross-check) | 0 | 0 | 254 | By design: PIA inline gate skips Step B; L4 is operator-invoked. |
| parity_check (sum pp == summary.rtp) | 0 | 0 | 254 | All `na` — per-pid breakdown not surfaced at summary granularity in this schema. |
| schema_ok / fields_present / gate_struct / rtp_is_number | 254 | 0 | 0 | Infrastructure clean. |
| eff_ver_format_ok | 252 | 2 | 0 | M278, M280 — manifest absent (see §4). |

**Top L2 failures, by bucket frequency** (88 bucket occurrences across
59 machines):

| Bucket | Count | Pattern |
|---|---|---|
| `_unattributed_residual` | 22 | Chunk-level sum gap — attribution rule reaches end of chunk with leftover credits. |
| `_unattributed_st2` | 17 | A specific bonus-ST that the paid-spin rule isn't claiming. |
| `_unattributed_st140` | 8 | BCM-family bonus ST. |
| `_unattributed_st126` | 7 | BCM-family bonus ST. |
| `_unattributed_st51` | 4 | Tight 4-machine cluster (M43/M44/M54/M75) — shared family. |
| `_unattributed_st68/125/130/137/154/156` etc. | 1-2 each | Long tail. |

---

## §3 Tier prediction accuracy

Walking §3 of `09_architecture_as_built.md` against the verifier rows:

### Tier 1 — predicted-hard (7 machines): 5/7 confirmed hard

| Machine | Predicted | Actual L2 | Verdict |
|---|---|---|---|
| **M250** | hard | fail (`st140`, `st2`) | Confirmed; "didn't recognize" bucket present as predicted. |
| **M260** | hard | fail (`st156`, `st2`, `residual`) | Confirmed. |
| **M264** | hard | fail (`st140`, `st126`, `residual`) | Confirmed. |
| **M268** | hard | fail (`st140`, `st125`) | Confirmed. |
| **M279** | hard | fail (`st2`) | Confirmed — narrower than expected after the 2026-04 BCM rework, only `st2` now leaks. |
| **M274** | hard (baseline must stay clean) | **pass** (RTP 95.80) | Architecture preserved baseline. |
| **M99** | hard (ST=97+98 dedupe open) | **pass** (RTP 91.12) | Surprise-clean — dedupe issue may be masked at the summary level; needs operator review at the round-table layer to confirm. |

### Tier 2 — structural outliers (18 machines): 6/18 actually-hard

- **Failed L2**: M12, M15, M39, M90, M132, M206, M272 — all in the
  trigger-session or BCM clusters that the prediction expected to
  flag at L2.
- **Passed**: M14, M32, M86, M99, M116, M120, M123, M201, M210, M257,
  M273. The architecture's "structural skip at L4" framing isn't
  visible at L2; for these the inline gate is clean.

### Tier 3 — listed in v5 but no documented issue (6 machines): 1/6 hard

- **M11**: fail (`st11`). The prediction said skip-until-surfaced. It
  surfaced. Move M11 to Tier 2 in a future revision.
- **M21, M65, M67, M108, M113**: all pass — prediction holds, no
  action needed.

### Surprises (L2-fail and NOT in Tier 1 or Tier 2): 47 machines

Most surprises group into shaped clusters that the Tier list missed:

- **`st2`-only cluster** (10 surprises: M147, M163, M219, M227, M232,
  M233, M239, M259, M267 + M279 from Tier 1) — a single bonus-ST
  rule is missing for a wide family.
- **`st51` cluster** (M43, M44, M54, M75) — 4 machines with the same
  signature, almost certainly a shared paytable family.
- **`residual`-only cluster** (12 surprises: M24, M110, M121, M125,
  M151, M158, M204, M243 + M12, M15, M90, M132 from Tier 2) — these
  are chunk-sum residuals, a different failure mode than per-ST.
- **BCM-extension cluster** (M262, M263, M266, M271, M244, M245, M247,
  M248) — same ST family (st126, st140, st130, st137) as Tier 1's
  M260/M264/M268, suggesting the BCM rule gap is broader than the
  documented 4-machine subset.
- **Singletons** (M76, M93, M97, M100, M138, M214, M251, M254) — each
  has a unique ST bucket; per-machine review.

The Tier 1/2 list in `09_architecture_as_built.md` captures the
*severity peaks* but undercounts breadth. The BCM family is ~8
machines wide, not 3-4; the `st2` family is ~10 wide, not 1.

---

## §4 Surprise patterns

- **Schema-layer failures**: zero. Files are written correctly,
  effective_analyzer_version field is present where the manifest
  resolves. Architecture proved out at the file-format layer.
- **`effective_analyzer_version` empty / format error**: 2 machines.
  - **M278**: manifest file absent from
    `slot_designer/configs/machine_manifests/` (range 270-281: 278,
    280, 281 absent; 281 not in test).
  - **M280**: same root cause — manifest absent.
  - Both are config gaps, not dual-path regression. The dual-path bug
    from prior sessions does not appear to have recurred — every
    machine that has a manifest produced a populated
    `effective_analyzer_version`.
- **parity_check NA across the board**: not a regression. The current
  summary JSON granularity doesn't expose `per_pay_id_rtp_pp`
  alongside `summary.rtp` in a way the verifier can cross-check
  in-line; this needs a Phase 4 schema additions, then the verifier
  can flip parity from `na` to pass/fail.
- **M254 wild RTP (~11,378%)**: L1 passes (arithmetic internally
  consistent — same chunk_win attributed via legal routes) but the
  value is well outside any sane envelope, with `_unattributed_st154`
  + `_unattributed_residual` both firing. Per user direction we don't
  gate on value range. **Treat as upstream rawdata corruption OR
  an analyzer mechanism not characterized for ST=154.** Should be
  inspected before any downstream consumer treats the report as
  trustworthy.

---

## §5 Recommended investigation priorities

These are the smallest interventions that would flip the most
machines green. No code change is being proposed here — investigation
ranking only.

1. **`_unattributed_st2` rule** — flipping a single ST=2 attribution
   rule would unblock 10 machines (M147, M163, M219, M227, M232, M233,
   M239, M259, M267) plus reduce surface area on M279 and 4 others.
   This is the single highest-leverage fix.
2. **BCM family ST=126/140 rule** — M250, M260, M262, M263, M264,
   M266, M268, M270, M271 share BCM-style buckets. Tier 1 already
   flagged the family; the actual extent is ~8 machines wider than
   documented. One rule fix could move them collectively.
3. **`st51` 4-machine cluster** (M43, M44, M54, M75) — same bucket
   signature across 4 machines is a fingerprint of a shared
   un-modeled paytable feature. Inspect one, fix one, all four flip.
4. **M276 sampling failure** — separate from L2: rerun with diagnostic
   reel or upstream probe to find why max_chunks_reached fires before
   any spin lands. Likely upstream-data, not analyzer.
5. **M254 extreme RTP** — manual rawdata inspection before anyone
   relies on the number. Likely an unmodeled multiplier mechanism on
   ST=154 inflating credited wins.

Operator/QA first-touch queue: **M254 (sanity), M276 (sampling),
M278/M280 (regen manifests + rerun), then the ST=2 cluster.**

---

## §6 Closing — what this run did NOT cover

- **Mode 2 / 5 / 7**: not tested. Per memory `user_testing_machine.md`,
  only M14 mode 1 supports precise RTP monitoring; the other modes are
  outside this run's scope.
- **26 synthetic underlying templates** (M102, M116, ...): not fleet
  members, no first-class summary checks. Their representative variants
  were tested.
- **Per-machine manifest review** for the 182 `config_not_reviewed`
  machines: this run confirms the gate ran end-to-end, but L3
  (anchor coverage) is a weak signal until manifests are reviewed.
- **L4 rawdata cross-check (Step B)**: all 254 are `skip` by design.
  Operator-invoked CLI; not run inline.
- **parity_check at per-pid granularity**: schema doesn't surface
  per-pid pp alongside summary.rtp; needs Phase 4 schema work.

---

**What this test proved**: the new architecture (effective_analyzer_version
+ rtp_integrity_check + manifests + console wiring) works end-to-end on
**252/254 = 99.2%** of the fleet. The 2 exceptions (M278, M280) are
config gaps — missing manifests — not architectural gaps.

**What this test surfaced**: 59 machines have L2 calculation gaps where
the analyzer can't attribute some win to a known pay_id. Of those, 6
are already on Tier 1/2; the remaining 47 are surprises, most of which
cluster into a small number of shared-feature families (~3 rule fixes
could flip ~25 machines).
