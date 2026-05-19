# 06_resolution.md — P2-B1 carve resolution

## Status: P2-B1a SHIPPED · P2-B1b deferred to follow-up ticket

The original P2-B1 brief asked to carve **15 functions + 1 class + 8 constants**
out of `fresh_slotlab/player_impact_analyzer.py` (PIA) into a new module
`fresh_slotlab/analyzer/core/parser.py`. During Wave 1 of execution the
implementer agent was spawned twice and both invocations were disposed by the
runtime before any code landed (TaskOutput returned `"No task found"` for both
`a9ee17c19689c242d` and `a7552feded62f9338`). Root cause: the 1857-line body of
`parse_chunk_response` was the bulk of the work and exceeded what one agent run
could finish inside its budget.

To unblock Phase 2 the ticket was sub-divided in the same style as the
P1-C1 resolution:

| Sub-ticket | Scope                                            | Status     |
|------------|--------------------------------------------------|------------|
| **P2-B1a** | 14 helpers + `ChunkIntegrityError` + 8 constants | **SHIPPED**|
| **P2-B1b** | `parse_chunk_response` (1857-line orchestrator)  | pending    |

P2-B1a was executed manually in the main session (no agent) because the work
was straightforward cut-and-paste once the carve plan was clear and the failed
agent attempts had already broken the per-agent budget.

---

## What landed in P2-B1a

### New files

- `fresh_slotlab/analyzer/core/__init__.py` — package marker, zero side
  effects (per memory `feedback_subprocess_import_suicide_and_module_globals.md`)
- `fresh_slotlab/analyzer/core/parser.py` — 405 lines containing the 14 helper
  functions, the `ChunkIntegrityError` exception, and the 8 module-level
  constants enumerated in the brief §1
- `tests/backend/test_analyzer_core_parser.py` — 1199-line regression suite
  written by the impl-tester agent during the first attempt; 93 tests covering
  C1-C8 contracts plus inject-bug coverage

### Modified files

- `fresh_slotlab/player_impact_analyzer.py` — 8126 → 7888 lines
  (-238 net). Added a 56-line dual-path import block at the top (try/except for
  package-mode vs script-mode) re-exporting all 23 symbols from
  `fresh_slotlab.analyzer.core.parser`. Original function/class bodies replaced
  with one-line `# moved to fresh_slotlab.analyzer.core.parser (P2-B1a)`
  markers so a grep for any symbol still finds the home file.

- `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` — Wave 2b status row
  updated; P2-B1b queued as the follow-up.

### Symbols carved

Functions (14):
`parse_rounds`, `_check_round_schema`, `parse_paylines`, `split_symbols`,
`parse_freespin_remarks`, `_compute_bonus_correction`,
`_compute_nf_correction`, `parse_rln_codes`, `_canonical_payload_bytes`,
`_payload_sha256`, `load_chunk_envelope`, `peek_chunk_envelope`,
`_compute_upstream_schema_fingerprint`, plus `PAYLINE_RE` consumers.

Class (1): `ChunkIntegrityError`.

Constants (8): `_BASELINE_ROUND_FIELDS`, `_REQUIRED_ROUND_FIELDS`,
`_REQUIRED_BET_FIELDS_ANY`, `_REMARKS_FREESPIN_RE`,
`_REMARKS_EXTRARATIO_RE`, `_REMARKS_ADDFREESPINS_COUNT_RE`,
`_ENVELOPE_PEEK_BYTES`, `_ENVELOPE_PEEK_RE`.

### Symbols still in PIA (deferred to P2-B1b)

- `parse_chunk_response` — 1857-line orchestrator that consumes every helper
  in `analyzer/core/parser.py`. Stays at PIA line 2304 for the moment.

---

## Verification (Wave 2 equivalent)

Subprocess smoke:
```
python -c "import fresh_slotlab.analyzer.core.parser"  # rc=0, no stderr
```

Identity check (re-export integrity, sample):
```
pia.parse_rounds            is core_parser.parse_rounds             -> True
pia.load_chunk_envelope     is core_parser.load_chunk_envelope      -> True
pia.ChunkIntegrityError     is core_parser.ChunkIntegrityError      -> True
pia._payload_sha256         is core_parser._payload_sha256          -> True
pia._ENVELOPE_PEEK_RE       is core_parser._ENVELOPE_PEEK_RE        -> True
```

Test suites (regression canary set per brief §3 C6):

| Suite                                                                | Result                  |
|----------------------------------------------------------------------|-------------------------|
| `tests/backend/test_analyzer_core_parser.py`                         | 82 passed · 7 skipped · 2 xfailed |
| `tests/integration/test_analyzer_three_invocation_parity.py` (P1-A1) | 23 passed               |
| `tests/backend/test_lookup_machine_md5_canonical.py` (P1-B1)         | passed (part of 225)    |
| `tests/backend/test_summary_md5_writer_parity.py` (P1-A2)            | passed (part of 225)    |
| `tests/backend/test_analyzer_foundation.py` (P2-A1)                  | passed (part of 225)    |
| `tests/backend/test_manifest_loader.py` (P2-A2)                      | passed (part of 225)    |

The **P1-A1 3-invocation parity test is the architectural canary** (per brief
§3 C2): all three invocation paths (CLI subprocess, in-process orchestrator,
batch worker) still produce byte-identical M14 mode 1 summaries against the
cached fixture. Carve did not perturb any user-visible behavior.

### xfail bookkeeping

Two tests in `test_analyzer_core_parser.py` are marked
`@pytest.mark.xfail(strict=True)` with reason `"deferred to sub-ticket
P2-B1b"`:

- `test_parse_chunk_response_is_callable`
- `test_parse_chunk_response_is_same_object_via_re_export`

`strict=True` means they auto-flip to PASS the moment P2-B1b lands and the
re-export wires up. The author of P2-B1b must remove the xfail decorators —
strict mode forces the conversation rather than letting them silently turn
xpassed.

The `_REQUIRED_FUNCTIONS_AND_CLASSES` parametrize list also has the
`"parse_chunk_response"` entry commented out with the same deferred reason.
Same instruction for the P2-B1b author: restore the entry when the function
ships.

---

## Self-critique

### Why sub-divide instead of retrying with a fresh agent

Two implementer agents had already died on the 1857-line carve. A third
attempt would have eaten more wall-time on the same failure mode without
shipping anything. Carving the helpers first (small, low-risk) unblocks the
rest of Wave 2b: `aggregator.py`, `writer.py`, and `base_pipeline.py` can all
proceed against a stable `core/parser.py` API without waiting on the
parse_chunk_response carve.

### Why no impl-tester refresh

The tester agent wrote the test file during the first attempt and that file
is already correct for P2-B1a (with the two xfails noted above). Re-running
tester would have wasted cycles producing the same file.

### What this resolution does NOT do

- Does not refactor any helper internals — pure cut/paste per §4 out-of-scope.
- Does not split `parse_chunk_response` — that is a separate Wave 2b sub-ticket.
- Does not delete `compute_analyzer_version` legacy — still deferred per the
  original brief.

### Risk to next ticket

`core/parser.py` is now the API boundary. P2-B1b carving
`parse_chunk_response` will need to import all 23 symbols back from
`core/parser.py` (the helper API). That is the cycle-risk path called out in
the brief §6 "Cycle risk" paragraph — P2-B1b implementer must verify no
parser→PIA back-import sneaks in via `parse_chunk_response`'s body.
