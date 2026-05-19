# Ticket P2-B2 — Carve `analyzer/core/aggregator.py` + create `core/_utils.py`

> Phase 2 / Wave 2b second carve. **MEDIUM-HIGH risk** — 16 symbols out of PIA
> plus the dedup of 9 duplicated helpers in `core/parser.py` left behind by
> P2-B1b.

---

## §1 Ticket scope

**Two files created**:

### `fresh_slotlab/analyzer/core/aggregator.py` (NEW — primary deliverable)

The 16 aggregation symbols from PHASE_2_TICKETS.md Wave 2b row P2-B2:

Bankruptcy (7):
- `_BankruptcyStreamAccumulator`
- `simulate_bankruptcy_from_response`
- `compute_bankruptcy_percentiles`
- `fastest_bankruptcy_spins_from_list`
- `median_spins_from_list`
- `_empty_bankruptcy_tier`
- `_extract_bankruptcy_reps`

Bucket rows (3):
- `build_multiplier_bucket_rows`
- `return_bucket`
- `quantile_from_hist`

Classifiers (2):
- `classify_volatility`
- `classify_experience_archetype`

Guideline comparison (4):
- `_metric_path_get`
- `_eval_operator`
- `_deviation`
- `evaluate_guideline_comparison`

Plus related constants (bankruptcy defaults already duplicated in parser.py;
they belong here): `_DEFAULT_BANKROLL_MULTIPLIERS`,
`_DEFAULT_BANKRUPTCY_SESSION_SPINS`.

### `fresh_slotlab/analyzer/core/_utils.py` (NEW — shared utility module)

The 9 helpers that P2-B1b duplicated into `core/parser.py` to break the
cycle. Three of these are pure utilities with no aggregator-aggregator
affinity (`to_float`, `blank_like_symbol`, `bonus_chain_depth_bucket`); the
other 6 are bankruptcy/bucket helpers but live close enough to pure utility
that both parser and aggregator legitimately need them.

Putting them in `_utils.py` (rather than aggregator.py) means parser does
NOT have to import from aggregator (which would invert the data-flow
direction; parser is upstream of aggregator).

Carve into `_utils.py`:
- `to_float`
- `blank_like_symbol`
- `bonus_chain_depth_bucket`
- `return_bucket`  ← MOVE-OUT-OF aggregator scope; goes in `_utils.py` instead
- `_empty_bankruptcy_tier`
- `_extract_bankruptcy_reps`
- `simulate_bankruptcy_from_response`
- `_DEFAULT_BANKROLL_MULTIPLIERS`
- `_DEFAULT_BANKRUPTCY_SESSION_SPINS`

Then `aggregator.py` imports those 9 from `_utils.py` and exposes the other
13 of its 16 scoped symbols. (Note: `return_bucket`, `_empty_bankruptcy_tier`,
`_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response`,
`_DEFAULT_BANKROLL_MULTIPLIERS`, `_DEFAULT_BANKRUPTCY_SESSION_SPINS` moved
out of aggregator's local scope into `_utils.py` — that is the
P2-B2-prerequisite dedup step.)

### `fresh_slotlab/analyzer/core/parser.py` (MODIFIED — dedup)

Delete the 9 duplicate definitions at parser.py lines ~441-475, ~507-630.
Replace with one import line:
```
from fresh_slotlab.analyzer.core._utils import (
    to_float, blank_like_symbol, bonus_chain_depth_bucket,
    return_bucket, _empty_bankruptcy_tier, _extract_bankruptcy_reps,
    simulate_bankruptcy_from_response,
    _DEFAULT_BANKROLL_MULTIPLIERS, _DEFAULT_BANKRUPTCY_SESSION_SPINS,
)
```
(Dual-path import for script-mode compat per the P2-B1a pattern at top of
parser.py.)

### `fresh_slotlab/player_impact_analyzer.py` (MODIFIED — re-exports)

Add to the existing dual-path import block at the top of PIA: re-exports for
the 16 aggregator symbols, so `pia.simulate_bankruptcy_from_response` etc.
still resolve. Delete the original definitions from PIA body, replace each
with a one-line `# moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)`
or `# moved to fresh_slotlab.analyzer.core._utils (P2-B2)` marker.

### `tests/backend/test_analyzer_core_aggregator.py` (NEW — regression suite)

Mirror the structure of `test_analyzer_core_parser.py`. C1-C8 contracts +
inject-bug TDD.

---

## §2 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 1`
  — "Carve core/ (4 files)"; aggregator.py is the second of the four.
- `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` Wave 2b row P2-B2 — 16
  symbols listed.
- `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` **DEDUP PREREQUISITE**
  row appended after P2-B1b — names the 9 duplicates that must be
  consolidated in this ticket.
- Memory `feedback_no_parallel_panel_impl.md` — the 9 duplicates are exactly
  the parallel-impl pattern the memory warns against; this ticket fixes it.
- Memory `feedback_prefer_complex_better.md` — `_utils.py` is the
  complex-but-better option vs the original "aggregator.py only" scope; this
  ticket takes it.
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — both
  new files must be import-safe.

---

## §3 Contract (testable invariants)

### C1 — Files exist + symbols carved
After ticket:
- `fresh_slotlab/analyzer/core/aggregator.py` present with the 13
  aggregator-only symbols (16 minus the 3 that went to `_utils.py`).
- `fresh_slotlab/analyzer/core/_utils.py` present with the 9 shared helpers.
- PIA re-exports the 16 P2-B2 symbols + the 9 (parser.py was already
  carrying these via its top dual-path import block; ensure PIA still
  re-exports them either directly from `_utils.py` or transitively through
  the existing import block).

### C2 — `pia.main()` unchanged behavior (P1-A1 canary stays GREEN)
`tests/integration/test_analyzer_three_invocation_parity.py` 23/23 GREEN.

### C3 — Single source of truth
After this ticket:
- `return_bucket` exists in exactly ONE place: `_utils.py`. (Was duplicated
  in parser.py + PIA after P2-B1b; this commit deletes both copies and
  centralizes.)
- Same for `to_float`, `blank_like_symbol`, `bonus_chain_depth_bucket`,
  `_empty_bankruptcy_tier`, `_extract_bankruptcy_reps`,
  `simulate_bankruptcy_from_response`,
  `_DEFAULT_BANKROLL_MULTIPLIERS`, `_DEFAULT_BANKRUPTCY_SESSION_SPINS`.
- Test asserts `inspect.getfile(pia.return_bucket).endswith("_utils.py")` AND
  `inspect.getfile(core_parser.return_bucket).endswith("_utils.py")`. (Both
  resolve to the same source file because both are re-exporting from
  `_utils.py`.)

### C4 — Subprocess import safety
- `python -c "import fresh_slotlab.analyzer.core._utils"` rc=0.
- `python -c "import fresh_slotlab.analyzer.core.aggregator"` rc=0.

### C5 — Cycle freedom
- `core/_utils.py` MUST NOT import from `core/parser.py`,
  `core/aggregator.py`, or `fresh_slotlab.player_impact_analyzer`. Standard
  library + stdlib `typing` only.
- `core/aggregator.py` MUST NOT import from
  `fresh_slotlab.player_impact_analyzer`. May import from `core/_utils.py`
  and `core/parser.py` (parser is upstream of aggregator in the pipeline).
- `core/parser.py` MUST NOT import from `core/aggregator.py` (wrong
  direction). It may newly import from `core/_utils.py` (that is the dedup).

### C6 — Hash composition rolls forward
`compute_base_analyzer_version()` already hashes `core/*.py`. Adding
`_utils.py` and `aggregator.py` to the set MUST flip the base hash
deterministically. Test: edit one byte in `_utils.py` → hash flips.

### C7 — All existing tests pass
- 5 Phase 1+2 regression suites listed in P2-B1b §3 C6, all GREEN.
- `tests/backend/test_analyzer_core_parser.py`: 87 passed expected
  (P2-B1b state) → after dedup the 9 inspect-getsource-equal assertions
  must be re-thought: parser.py's `return_bucket` is now an alias for
  `_utils.return_bucket`. If the P2-B1b verifier wrote a "duplicates have
  is-distinct objects" test, it must be marked superseded or modified to
  assert is-SAME-after-dedup.
- `tests/backend/test_analyzer_core_aggregator.py` (new): 60+ tests expected.

### C8 — Inject-bug TDD
- Inject: re-add a local `def to_float(...)` to parser.py that does
  something different → assertion that all import paths resolve to
  `_utils.to_float` goes RED.
- Inject: add a `from fresh_slotlab.analyzer.core.aggregator import X`
  inside `core/_utils.py` → cycle test RED.

---

## §4 Out of scope

- `parse_chunk_response` body refactor (still pure carve from P2-B1b).
- Writer logic (P2-B3).
- HTTP / base_pipeline (P2-B4).
- Frontend changes.
- Removing legacy `compute_analyzer_version`.

---

## §5 Rollback path

Single commit. `git revert <sha>` restores PIA's 16 symbols + parser.py's 9
duplicates + deletes `_utils.py` and `aggregator.py`. Re-export lines
disappear; existing callers fall back to PIA's restored implementations.

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM-HIGH. Three risks:

1. **Dedup must be atomic.** Removing 9 duplicates from parser.py and adding
   them to `_utils.py` MUST happen in the same commit. If either half lands
   alone parser.py either has 2 copies or 0 copies (both NameError-class
   bugs).

2. **Bankruptcy stack interplay.** `_BankruptcyStreamAccumulator` is a
   stateful class; `simulate_bankruptcy_from_response` constructs instances;
   `compute_bankruptcy_percentiles` consumes them; `_extract_bankruptcy_reps`
   parses upstream payload bankruptcy fields. The dependency chain must
   stay consistent across the carve. Test must exercise an end-to-end
   bankruptcy simulation on a fixture (or via P1-A1 parity, which already
   does).

3. **Re-export interactions with parser.py.** parser.py's existing dual-path
   import block re-exports 23 symbols from itself. After P2-B2:
   - parser.py imports from `_utils.py` (new dep)
   - PIA imports from parser.py (existing)
   - PIA also imports from aggregator.py (new)
   - PIA also imports from `_utils.py` (new, transitively through parser is
     also fine but a direct re-export is more readable)

   Implementer should follow the established dual-path pattern in PIA's
   import block exactly — do NOT invent a new style.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — does the 3-way carve in one commit: creates
  `_utils.py`, creates `aggregator.py`, deletes parser.py duplicates +
  adds `_utils` import, deletes PIA bodies + adds 25 (16+9) re-exports.
  Runs P2-B1b suite + canary to confirm.
- `impl-tester` — writes `test_analyzer_core_aggregator.py` covering C1-C8
  for aggregator + the "single source of truth" assertion that the 9
  formerly-duplicated symbols resolve to `_utils.py` from every entry
  point (PIA, parser.py, aggregator.py). Inject-bug for each contract.

### Wave 2 (parallel)
- `impl-verifier` — full regression set + P1-A1 canary + subprocess smoke
  + cycle grep + dedup verification (each of 9 symbols resolves to
  `_utils.py` from 3 entry points).
- `impl-critic` — adversarial: did the carve respect the data-flow
  direction? Are the 9 helpers really pure utilities or did one of them
  drag aggregator state? Is the bankruptcy stack actually atomic across
  the carve? Did parser.py's existing P2-B1b regression file need
  updating (the `is_diff=True` divergence-audit test now needs to flip
  to `is_diff=False`)?

Expected wall time: ~100-140 min. Slightly more than P2-B1b because of the
3-way file split + the dedup re-test in parser.py.
