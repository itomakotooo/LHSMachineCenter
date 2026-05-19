# Ticket P2-B1b — Carve `parse_chunk_response` into `analyzer/core/parser.py`

> Phase 2 / Wave 2b follow-up to P2-B1a. **HIGH risk** — single 1857-line
> function move; the carve that took down two implementer agents during the
> first P2-B1 attempt.

---

## §1 Ticket scope

P2-B1a already carved the helpers + constants + `ChunkIntegrityError` out of
`fresh_slotlab/player_impact_analyzer.py` (PIA) into
`fresh_slotlab/analyzer/core/parser.py`. The only symbol that did not move
was the orchestrator `parse_chunk_response` (PIA line 2304 in the post-P2-B1a
file). This ticket finishes the carve.

Files expected to change:
- `fresh_slotlab/analyzer/core/parser.py` (append `parse_chunk_response` body)
- `fresh_slotlab/player_impact_analyzer.py` (delete the function body; add a
  re-export line for `parse_chunk_response` to the existing dual-path import
  block near the top of the file)
- `tests/backend/test_analyzer_core_parser.py` (remove the two xfail
  decorators + restore `"parse_chunk_response"` to the
  `_REQUIRED_FUNCTIONS_AND_CLASSES` parametrize list)

**Function to move**:
- `parse_chunk_response` — ~1857 lines starting at the post-P2-B1a PIA line
  (was 2304 pre-P2-B1a; the helper deletions shifted it; implementer must
  re-locate via `grep -n "^def parse_chunk_response" pia` before cutting)

**Out of scope** (stays in PIA):
- `pia.main()` orchestrator
- HTTP layer (P2-B4)
- Aggregation (P2-B2)
- Writer (P2-B3)

---

## §2 Brief sections cited

Same as P2-B1: §6.2 deliverable 1, §4.1 hash composition, §5.8 thin
orchestrator. Plus:
- `session_artifacts/_impl/phase2/03_core_parser/06_resolution.md` —
  documents why the original P2-B1 was split and what was already shipped in
  P2-B1a; this ticket is the second half.

---

## §3 Contract (testable invariants)

### C1 — `parse_chunk_response` lives in `core/parser.py`
After ticket:
- `fresh_slotlab/analyzer/core/parser.py` has a top-level `def
  parse_chunk_response(...)` matching the pre-carve signature byte-for-byte.
- PIA contains a re-export line `parse_chunk_response =
  _core_parser.parse_chunk_response` (or equivalent — match the existing P2-B1a
  re-export pattern in the dual-path import block).
- `fresh_slotlab.player_impact_analyzer.parse_chunk_response is
  fresh_slotlab.analyzer.core.parser.parse_chunk_response` evaluates True.

### C2 — `pia.main()` unchanged behavior (P1-A1 3-invocation parity stays GREEN)
The Phase 1 P1-A1 parity test must stay green post-carve. All 3 invocation
paths produce byte-identical summary against the M14 mode 1 cached fixture.

### C3 — Cycle freedom
`parse_chunk_response` body MUST NOT import from
`fresh_slotlab.player_impact_analyzer` (would create a cycle since PIA
imports from `core.parser`). All cross-references must resolve to either:
- another symbol already in `core/parser.py` (preferred), or
- a primitive in the Python standard library, or
- a future plugin/feature module from Wave 2c onward.

If a reference inside `parse_chunk_response` reaches into a symbol that is
still in PIA (e.g. aggregator helpers, writer functions) and that symbol is
slated for a later P2-B2/B3/B4 carve, the cleanest fix is to **pass it as
an argument** rather than importing back. Lazy imports inside the function
body are an acceptable last resort but should be the exception.

### C4 — xfail decorators removed
`tests/backend/test_analyzer_core_parser.py` no longer has any
`@pytest.mark.xfail` markers tied to `parse_chunk_response`. The
parametrize list `_REQUIRED_FUNCTIONS_AND_CLASSES` includes
`"parse_chunk_response"`. Both xfail tests now PASS.

### C5 — Hash composition rolls forward
`compute_base_analyzer_version()` hashes `core/*.py`. After this ticket the
parser.py hash MUST change (carved function adds ~1857 lines). Test in
`test_analyzer_foundation.py` will catch deterministic hash flip on edit.

### C6 — All existing tests pass
- `tests/integration/test_analyzer_three_invocation_parity.py` (P1-A1)
- `tests/backend/test_lookup_machine_md5_canonical.py` (P1-B1)
- `tests/backend/test_summary_md5_writer_parity.py` (P1-A2)
- `tests/backend/test_analyzer_foundation.py` (P2-A1)
- `tests/backend/test_manifest_loader.py` (P2-A2)
- `tests/backend/test_analyzer_core_parser.py` (P2-B1a; with xfails removed)

### C7 — No error swallowing added
Per memory `feedback_dont_swallow_errors_in_fix.md`. Move preserves the
existing try/except structure of `parse_chunk_response`; no new silent
catches.

### C8 — Inject-bug TDD
- Inject: delete the re-export line in PIA → identity test goes RED.
- Inject: change one line inside the moved function body → core/* hash flips.
- Inject: add a back-import `from fresh_slotlab.player_impact_analyzer import
  X` at top of parser.py → subprocess smoke catches the cycle.

---

## §4 Out of scope

- Splitting `parse_chunk_response` into smaller functions (separate refactor).
- Touching helper APIs (P2-B1a froze them).
- Aggregator / writer / base_pipeline carves (P2-B2, P2-B3, P2-B4).
- Frontend changes.
- Removing legacy `compute_analyzer_version` (defer to P2-B4 if appropriate).

---

## §5 Rollback path

Single commit. `git revert <sha>` restores `parse_chunk_response` to its
post-P2-B1a PIA location and removes the re-export. The 23 helper re-exports
from P2-B1a stay intact — they are independent.

---

## §6 Risk + rollback notes

**Risk class**: HIGH. The function is ~1857 lines and consumes many helpers.
Implementer must:
1. Find the post-P2-B1a location: `grep -n "^def parse_chunk_response"
   fresh_slotlab/player_impact_analyzer.py`.
2. Read the entire function body in chunks (likely 5-6 Read calls at 400 lines
   each).
3. Append it verbatim to `fresh_slotlab/analyzer/core/parser.py`.
4. Delete the body from PIA, replace with a one-line `# moved to ...
   (P2-B1b)` comment.
5. Add `parse_chunk_response = _core_parser.parse_chunk_response` to the
   existing dual-path import block in PIA.
6. Verify cycle freedom: `grep -n "from fresh_slotlab.player_impact_analyzer"
   fresh_slotlab/analyzer/core/parser.py` MUST return zero matches.
7. Remove the two xfail decorators in
   `tests/backend/test_analyzer_core_parser.py` and uncomment the
   `"parse_chunk_response"` entry in `_REQUIRED_FUNCTIONS_AND_CLASSES`.
8. Run pytest yourself before claiming pass (per memory
   `feedback_perf_claim_needs_e2e_event_stream.md`).

**Agent-disposal mitigation**: the original P2-B1 took down two implementer
agents on the all-in-one carve. P2-B1a unblocked the rest of the carve so
this single-function move is bounded. Implementer should still:
- Spawn with an aggressive read budget (5-6 Read calls planned upfront).
- Make the entire move in **one Edit-or-Write batch** — do not interleave
  multiple inserts/deletes that risk being only half-applied.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — perform the cut/paste; verify cycle freedom; remove
  xfails; re-run pytest locally.
- `impl-tester` — confirm xfail removal flips the two tests GREEN; add no
  new test files (the P2-B1a suite already covers the contract).

### Wave 2 (parallel)
- `impl-verifier` — run P1-A1 parity canary + 5 Phase 1+2 regression
  suites; subprocess smoke; cycle-grep.
- `impl-critic` — adversarial review on cycle introduction, lazy-import
  abuse, and hash composition correctness.

Expected wall time: ~60-90 min (now bounded; the helpers are already gone so
this is one Read → one Write → small Edits).
