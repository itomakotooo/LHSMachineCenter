# P2-B1b Implementation Report

**Ticket**: phase2/03b_core_parser_orchestrator  
**Verdict**: PASS  
**Implementer**: impl-implementer  
**Date**: 2026-05-19

---

## Files Changed

| File | Lines before | Lines after | Change |
|---|---|---|---|
| `fresh_slotlab/analyzer/core/parser.py` | ~405 (post-P2-B1a) | 2504 | +~2099 lines (utility copies + `parse_chunk_response`) |
| `fresh_slotlab/player_impact_analyzer.py` | ~7889 | 6035 | -1855 lines (function body replaced with 1-line comment) |
| `tests/backend/test_analyzer_core_parser.py` | 1230 | 1229 | -2 xfail decorators; `"parse_chunk_response"` added to parametrize list |

---

## Brief-Section Traceability

| Change | Brief section |
|---|---|
| `parse_chunk_response` appended to `core/parser.py` | §1 "Files expected to change", §3 C1 |
| Utility functions `to_float`, `blank_like_symbol`, `bonus_chain_depth_bucket`, `return_bucket` copied to `parser.py` | §3 C3 "pass as argument / copy" to break cycle |
| Bankruptcy helpers `_DEFAULT_BANKROLL_MULTIPLIERS`, `_DEFAULT_BANKRUPTCY_SESSION_SPINS`, `_empty_bankruptcy_tier`, `_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response` copied to `parser.py` | §3 C3 cycle freedom |
| Dual-path imports added to `parser.py` for `trigger_sessions`, `round_classification`, `round_win` | §3 C3 "primitives from other fresh_slotlab modules" |
| PIA function body (lines 2067-3921, 1855 lines) replaced with `# parse_chunk_response moved to fresh_slotlab.analyzer.core.parser (P2-B1b)` | §6 step 4 |
| PIA dual-path import block comment updated; `parse_chunk_response` added to both `try:` and `except ImportError:` branches | §3 C1 re-export; §6 step 5; pattern matching `parse_rounds`/`load_chunk_envelope` |
| Two `@pytest.mark.xfail(strict=True, ...)` decorators removed; `"parse_chunk_response"` added to `_REQUIRED_FUNCTIONS_AND_CLASSES` | §3 C4; §1 "Files expected to change" |

---

## Cycle Freedom Verification

`grep -n "fresh_slotlab.player_impact_analyzer" fresh_slotlab/analyzer/core/parser.py` returns **zero matches**.

Resolution of cross-references inside `parse_chunk_response` that would have created a cycle:
- `to_float`, `blank_like_symbol`, `bonus_chain_depth_bucket`, `return_bucket`: pure utility functions with no dependencies; copied verbatim from PIA. PIA retains its own definitions (no identity check required for these — only `parse_chunk_response` itself has the `is` check per C1/C3).
- `_DEFAULT_BANKROLL_MULTIPLIERS`, `_DEFAULT_BANKRUPTCY_SESSION_SPINS`, `_empty_bankruptcy_tier`, `_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response`: bankruptcy infrastructure; copied verbatim. PIA retains its own definitions.
- `compute_trigger_sessions`, `detect_cycle_peak`, `is_wild_nudge_round`, `RoundWinRule`, `extract_round_win`, `extract_round_payouts`: imported via dual-path block from `fresh_slotlab.trigger_sessions`, `fresh_slotlab.round_classification`, `fresh_slotlab.round_win` — none of these import from PIA, so no cycle.

---

## Pytest Results

```
tests/backend/test_analyzer_core_parser.py          87 passed, 7 skipped
tests/backend/test_analyzer_foundation.py           (included in full run)
tests/backend/test_manifest_loader.py               (included in full run)
tests/backend/test_lookup_machine_md5_canonical.py  (included in full run)
tests/backend/test_summary_md5_writer_parity.py     (included in full run)
tests/integration/test_analyzer_three_invocation_parity.py  23 passed

Full combined run: 335 passed, 7 skipped, 0 failed in 22.59s
```

The 7 skipped tests are pre-existing skips (not related to P2-B1b).

---

## Contract Verification

| Contract | Status | Evidence |
|---|---|---|
| C1 — `parse_chunk_response` in `core/parser.py` | PASS | `hasattr(_core_parser_mod, 'parse_chunk_response')` — test passes |
| C1 — PIA re-exports `parse_chunk_response` | PASS | `hasattr(_pia, 'parse_chunk_response')` — test passes |
| C1 — Signature byte-for-byte match | PASS | `inspect.signature` confirms 7 params: `resp, chunk_index, bet, started, bankruptcy_session_spins, bankruptcy_bankroll_mults, round_win_rules` |
| C2 — `pia.main()` parity unchanged | PASS | 23/23 three-invocation parity tests GREEN |
| C3 — Cycle freedom | PASS | grep returns 0 matches |
| C3 — Identity: `pia.parse_chunk_response is cp.parse_chunk_response` | PASS | Python assertion confirmed at runtime |
| C4 — xfail decorators removed | PASS | Both tests now PASS (not xfail) |
| C5 — Hash composition rolls forward | PASS | `parser.py` grew from ~405 to 2504 lines; `compute_base_analyzer_version()` hashes all `core/*.py` files — hash will differ |
| C6 — All existing tests pass | PASS | 335 passed across all 6 suites |
| C7 — No error swallowing added | PASS | `parse_chunk_response` body copied verbatim; no new `except: pass` added |

---

## Implementation Method Notes

The function body replacement in PIA was done via Python line-number surgery (not Edit tool) because the 1855-line body cannot be represented as a unique old_string for the Edit tool. The surgery:
1. Read all 7889 lines into memory
2. Verified line 2067 = `def parse_chunk_response(` (0-indexed 2066)
3. Verified line 3921 = `    }` — closing dict (0-indexed 3920)
4. Replaced lines[2066:3921] with the one-line comment
5. Wrote back; verified new total = 6035 lines, `def main()` at line 2070

The Edit tool was used for all other changes (dual-path import block in PIA, xfail removals in test file, parametrize list update).

---

## Open Issues / Out of Scope

None — all contracts met.

Items deferred per §4 (out of scope for this ticket, not implemented):
- Splitting `parse_chunk_response` into smaller functions — separate refactor
- Aggregator / writer / base_pipeline carves (P2-B2, P2-B3, P2-B4)
- Removing legacy `compute_analyzer_version` (defer to P2-B4)

---

## Risk Notes for impl-verifier / impl-critic

1. **Copied utilities in parser.py**: `to_float`, `blank_like_symbol`, `bonus_chain_depth_bucket`, `return_bucket`, `_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response`, and related constants now exist in both PIA and `parser.py`. This is intentional (cycle break); they are NOT re-exports — they are copies. The `is` identity check only applies to `parse_chunk_response` itself. Any future refactor that wants single-definition for these utilities belongs to P2-B2/B3/B4 carves, not this ticket.

2. **`return_bucket` test at line 1223**: The test file has a comment saying `return_bucket` is "NOT in the carve list; it must stay in PIA". PIA retains its own `def return_bucket` at line 1784. The copy in `parser.py` is used internally by `parse_chunk_response` — the test only asserts PIA has it, which is still true.

3. **Subprocess mode**: The three-invocation parity test (Path A = subprocess) exercises `parse_chunk_response` end-to-end via real subprocess against M14 mode 1 cached fixtures. All 3 paths produce byte-identical summaries — this is the strongest behavioral proof that the carve did not alter semantics.
