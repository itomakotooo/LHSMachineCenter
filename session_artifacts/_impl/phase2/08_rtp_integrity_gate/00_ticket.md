# Ticket P2-E1 — `rtp_integrity.py` 4-layer gate (warn-only mode)

> Phase 2 Wave 2e first deliverable. The operator's diagnostic surface
> per §9.1. Warn-only mode by default per the handoff.

---

## §1 Ticket scope

Create `fresh_slotlab/analyzer/rtp_integrity.py` implementing the 4-layer
RTP integrity check per `04_architecture_proposal_v5.md §9`.

Public API:

```python
@dataclass(frozen=True)
class RTPIntegrityResult:
    machine: str
    mode: int
    passed: bool
    layer1_invariant_ok: bool
    layer1_error: str | None
    layer2_no_fallback_buckets_ok: bool
    layer2_fallback_buckets_found: list[str]
    layer3_anchors_ok: bool
    layer3_missing_anchors: list[str]
    layer4_applicable: bool
    layer4_per_st_consistency_ok: bool | None
    layer4_inconsistencies: list[dict]
    layer4_skip_reason: str | None
    summary_message: str
    suggested_actions: list[str]
    completeness_declared: bool


def check_rtp_integrity(
    summary: dict,
    *,
    manifest: dict | None = None,
    rawdata_dir: Path | None = None,
    warn_only: bool = True,
) -> RTPIntegrityResult: ...


def main() -> int:  # CLI: rtp_integrity --machine M --mode N
    ...
```

Implementation layers per §9:

- **Layer 1** (invariant): `sum(payout_id_win[pid]) == chunk_win` across all chunks.
- **Layer 2** (fallback prefixes): no payout_id starts with `_unattributed_`, `_other`, `_default`, or `_misc`.
- **Layer 3** (anchor coverage): manifest's `required_attribution_anchors` all have >0 hits.
- **Layer 4** (rawdata cross-check): gated by `manifest.layer4_applicable`. Step A/B/C per §9.4 spec.

---

## §2 Brief sections cited

- `04_architecture_proposal_v5.md §9` (lines 1003-1300) — full spec.
- `04_architecture_proposal_v5.md §5.5.6` — manifest schema for
  `rtp_integrity_contract` field.
- Memory `feedback_invariant_with_fallback_hides_drift.md` — Layer 2's
  rationale.
- Memory `feedback_no_silent_swallow.md` — never silently swallow gate result.
- Phase 2 handoff §4 — "warn-only mode by default".

---

## §3 Contract (testable invariants)

### C1 — File exists; API matches spec
`fresh_slotlab/analyzer/rtp_integrity.py` exposes
`RTPIntegrityResult` (frozen dataclass), `check_rtp_integrity(...)`,
and `main()` per §1.

### C2 — Layer 1 catches arithmetic drift
A synthetic summary where `sum(payout_id_win)` ≠ `chunk_win` → `passed=False`,
`layer1_invariant_ok=False`, `layer1_error` non-empty.

### C3 — Layer 2 catches `_unattributed_*` and similar fallback prefixes
A summary where one pay_id row has id starting with `_unattributed_` →
`passed=False`, `layer2_no_fallback_buckets_ok=False`,
`layer2_fallback_buckets_found` non-empty.

Reserved prefix list per §9.2 Layer 2: `_unattributed_`, `_other`,
`_default`, `_misc`.

### C4 — Layer 3 checks required anchors
A manifest specifying `required_attribution_anchors=["666"]` against a
summary where pay_id 666 has 0 hits → `layer3_anchors_ok=False`,
`layer3_missing_anchors=["666"]`.

### C5 — Layer 4 skip for trigger-session machines
A manifest with `layer4_applicable=False` (and/or
`trigger_session_pattern` non-null) → `layer4_applicable=False`,
`layer4_per_st_consistency_ok=None`, `layer4_skip_reason` populated,
and Step B/C NOT executed.

### C6 — Layer 4 Step A/B/C consistency
With `layer4_applicable=True` and a synthetic rawdata chunk where
`payout_id_by_spin_type_total` matches `PayoutIdToWinAmount.keys()` per
round → `layer4_per_st_consistency_ok=True`, `layer4_inconsistencies=[]`.

When the analyzer's `payout_id_by_spin_type_total` shows pid 100 in
ST=1 with count 5 but rawdata only shows pid 100 in ST=1 with count 3 →
inconsistency entry recorded with `(pid=100, st=1, a_count=5, f_count=3)`.

### C7 — Warn-only mode default
`check_rtp_integrity(..., warn_only=True)` (default) does NOT raise on
failure; returns the result with `passed=False`. With
`warn_only=False`, the same input raises `RTPIntegrityError`. Provides
both surfaces so Phase 5 policy flip can change a single bool.

### C8 — Subprocess import safety + CLI entrypoint
- `python -c "import fresh_slotlab.analyzer.rtp_integrity"` rc=0.
- `python -m fresh_slotlab.analyzer.rtp_integrity --help` rc=0 (CLI works).
- `python -m fresh_slotlab.analyzer.rtp_integrity --machine M14 --mode 1 --rawdata-dir rawdata/M14/mode_1` exits 0 if all applicable layers pass; non-zero with error JSON to stderr if any fail.

### C9 — All existing tests pass
- 10-suite Phase 1+2 regression: 715+ GREEN.
- New `tests/backend/test_rtp_integrity_gate.py` (~40+ tests).

### C10 — Inject-bug TDD
- Inject: change Layer 2 prefix list (e.g. drop `_unattributed_`) →
  L2 test RED. Revert: GREEN.
- Inject: change `warn_only=True` default to False → C7 test (warn-only
  no-raise) RED. Revert: GREEN.
- Inject: in Step C comparison, swap `a_count` and `f_count` → C6
  inconsistency test recorded with wrong values → fixture assertion
  RED.

---

## §4 Out of scope

- Per-machine manifest JSON files (Phase 3 deliverable).
- Wiring the gate into pia.main() summary build (Phase 5 — until then
  rtp_integrity.py is a standalone validator the operator runs against
  cached chunks).
- The 12 forcing-function machines onboarding (P2-E2..E13).
- Layer 4 mirror approach (out of scope per §9.4 trade-off; future).
- Frontend changes.

---

## §5 Risk + rollback

**Risk class**: LOW. New file; no existing PIA modifications. Worst
case: revert deletes the new file.

The rawdata cross-check (Layer 4 Step B) iterates chunk JSON files. For
a 10000-spin M14 fixture this is ~3 seconds per `04_v5 §9.4`. Acceptable
for an operator-invoked check.

---

## §6 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — write `fresh_slotlab/analyzer/rtp_integrity.py`
  per §1 API. Plus CLI in `if __name__ == "__main__":` block.
  Implement all 4 layers per §9. No I/O at import (memory
  feedback_subprocess_import_suicide_and_module_globals.md).

- `impl-tester` — write
  `tests/backend/test_rtp_integrity_gate.py` covering C1-C10. Use
  synthetic summaries / rawdata stubs for layers 1-3; use a tiny
  fixture chunk for Layer 4 Step B. Inject-bug for at least 3
  contracts.

### Wave 2 (parallel)
- `impl-verifier` — run the full regression + run the new CLI against
  M14 mode 1 cached fixture and confirm rc=0 (assuming M14 passes all
  layers per Validator v4).
- `impl-critic` — adversarial: does Layer 4 Step B actually iterate
  ALL chunk files (not just first)? Is `passed=True` only when ALL
  applicable layers pass (not just any)? Is the JSON error output
  per §9.3 byte-identical to the spec?

Expected wall time: ~80-110 min. Roughly: 4 layers × ~20 lines each +
dataclass + CLI + tests + inject-bug verification.
