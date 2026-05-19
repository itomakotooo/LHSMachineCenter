# P2-B4 Implementation Report — `analyzer/core/base_pipeline.py`

## Verdict: PASS

All 8 functions carved. Identity checks pass. Canary 23/23 GREEN. 8-suite
regression 496+128 = 624 passing.

---

## Files changed

| File | Change | Lines (before → after) |
|------|--------|------------------------|
| `fresh_slotlab/analyzer/core/base_pipeline.py` | CREATED | 0 → 619 |
| `fresh_slotlab/player_impact_analyzer.py` | MODIFIED | 5429 → 4994 |
| `fresh_slotlab/analyzer/core/__init__.py` | MODIFIED | +8 lines (base_pipeline entry) |
| `src/web_console/backend/app.py` | MODIFIED | +8 lines (monkeypatch fix) |

### PIA line ranges removed (approximate)

| Symbol | Removed from PIA |
|--------|-----------------|
| `DEFAULT_ENDPOINT_URL`, `ENDPOINT_URL` | Lines 233-241 |
| `DEFAULT_GUIDELINE_RULES_PATH` | Lines 289-291 |
| `parse_args` (body) | Lines 294-430 |
| `_RETRYABLE_HTTP_CODES` | Line 457 |
| AIMD constants (MIN_CHUNK_SPINS / SUCCESS_STREAK_FOR_GROW / CHUNK_SPINS_GROWTH / CIRCUIT_PAUSE_S) | Lines 519-522 |
| `_classify_failure` (body) | Lines 525-572 |
| `aimd_tune` (body) | Lines 987-1025 |
| `post_json_with_retry` (body) | Lines 1028-1089 |
| `select_replay_chunks_by_md5` (body) | Lines 1160-1214 |
| `make_payload` (body) | Lines 1277-1323 |
| `run_sampling_chunk` (body) | Lines 1392-1459 |

---

## ENDPOINT_URL strategy: Option B

Chosen Option B (move `ENDPOINT_URL` to `base_pipeline.py`; main() mutates
`_core_base_pipeline.ENDPOINT_URL` via setattr) per brief §3 C3.

Rationale: the function body of `post_json` is preserved byte-identical — it
reads `ENDPOINT_URL` from its own module namespace (`base_pipeline.ENDPOINT_URL`)
at call time, which is the live source of truth. `pia.ENDPOINT_URL` is a
snapshot-binding (copied at import time, not a reference to the live string),
so mutating the module attribute on `_core_base_pipeline` is the only way to
affect `post_json`'s behavior without touching call sites.

`main()` change:
```python
# before (PIA-local global):
global ENDPOINT_URL
if args.endpoint_url:
    ENDPOINT_URL = args.endpoint_url

# after (Option B):
if args.endpoint_url:
    _core_base_pipeline.ENDPOINT_URL = args.endpoint_url
```

---

## Dependencies resolved (no DI needed)

All 8 functions can import their dependencies directly from canonical modules:

| Dependency | Source | Cycle risk |
|------------|--------|-----------|
| `_DEFAULT_BANKROLL_MULTIPLIERS`, `_DEFAULT_BANKRUPTCY_SESSION_SPINS` | `core/_utils.py` | None |
| `parse_chunk_response` | `core/parser.py` | None |
| `_save_chunk_cache` | `core/writer.py` | None |
| `_rebuild_by_md5` | `fresh_slotlab.chunk_index` | None |
| `_lookup_machine_md5` | `fresh_slotlab.machine_md5` | None |
| `_rawdata_index_update_entry` | `fresh_slotlab.rawdata_index` | None |
| `RoundWinRule` | `fresh_slotlab.round_win` | None |

No dependency-injection pattern was needed for any of the 8 functions.

---

## Critical fix: app.py monkeypatch (§6 risk note 4)

After the carve, `run_sampling_chunk` calls `post_json_with_retry` → `post_json`
from `base_pipeline`'s module namespace. `_run_generate_report` in `app.py` was
monkeypatching only `pia.post_json` for the in-process replay path, which was
no longer seen by the carved `base_pipeline.post_json`.

Fix: also patch `_core_bp.post_json` (and restore it in the finally block).
The lambda is shared so both names point to the same stub.

This is the minimal-delta change to preserve the existing monkeypatch semantic
per brief §6 risk note 4 ("Move it cleanly with all its dependencies importable
from core/* or pass them as args"). The alternative (DI for post_json through
run_sampling_chunk) would require touching every callsite — that is out of scope
per brief §4.

---

## Shadow-def grep results (must be 0)

```
grep -n "^def parse_args|^def post_json|^def _classify_failure|..." PIA
→ 0 matches
```

---

## Cycle-freedom grep results (must be 0)

```
# base_pipeline must not import from PIA
grep -n "from fresh_slotlab.player_impact_analyzer" base_pipeline.py → 0

# core siblings must not import from base_pipeline
grep -rn "from fresh_slotlab.analyzer.core.base_pipeline" parser.py aggregator.py writer.py _utils.py → 0
```

---

## Pytest results

### P1-A1 canary (C2)
`tests/integration/test_analyzer_three_invocation_parity.py` — **23/23 PASS**

### 8-suite backend regression (C7)
```
test_lookup_machine_md5_canonical.py
test_summary_md5_writer_parity.py
test_analyzer_foundation.py
test_manifest_loader.py
test_analyzer_core_parser.py
test_analyzer_core_aggregator.py
test_analyzer_core_writer.py
```
→ **496 passed, 11 skipped**

### base_pipeline unit tests (C1/C3/C4/C5/C7/C8)
`tests/backend/test_analyzer_core_base_pipeline.py` — **128 passed, 2 skipped**

**Total: 647 passing (23 + 496 + 128)**

---

## Subprocess import safety (C4)

```
python -c "import fresh_slotlab.analyzer.core.base_pipeline"
→ exit code 0, no stderr
```

---

## Identity check (C1)

```python
pia.parse_args is bp.parse_args   → True
pia.post_json is bp.post_json     → True
pia.aimd_tune is bp.aimd_tune     → True
pia.run_sampling_chunk is bp.run_sampling_chunk → True
(all 8 checked)
```

---

## Brief-section traceability

| Code change | Brief section |
|-------------|---------------|
| Created `base_pipeline.py` with 8 functions + constants | §1, citing 04_v5 §6.2 deliverable 1 |
| ENDPOINT_URL Option B strategy | §3 C3 |
| No I/O at import time | §2 (memory `feedback_subprocess_import_suicide_and_module_globals.md`) |
| `aimd_tune` body byte-identical | §2 (memory `feedback_upstream_throttle_ceiling.md`) |
| PIA re-exports 8 symbols via dual-path import block | §3 C1 |
| Shadow-def grep = 0 | §6 (P2-B2 critic lesson on shadow defs) |
| Cycle-grep = 0 | §3 C5 |
| app.py monkeypatch fix | §6 risk note 4 |

---

## Open issues / deferred items

1. **`pia.ENDPOINT_URL` is a snapshot-binding** after the carve. Any code that
   does `from fresh_slotlab.player_impact_analyzer import ENDPOINT_URL` will get
   a stale string. This is pre-existing behavior (strings are immutable; the old
   `pia.ENDPOINT_URL = args.endpoint_url` only affected PIA-local callers
   anyway). The only actual caller is `post_json` (now in base_pipeline) which
   reads from `base_pipeline.ENDPOINT_URL` at call time — correct.

2. **`MAX_CONSECUTIVE_FAILED_BATCHES_NET` / `NON_CONVERGENCE_*` constants** stay
   in PIA (they are only used by `main()`). Not moved per §1 out-of-scope.

3. **C6 hash composition** — `compute_base_analyzer_version()` is not yet gating
   on `base_pipeline.py` being present. Same precedent as P2-B1b/B2/B3 (skipped
   in test suite). Deferred to when versioning.py exports the function.

---

## Risk notes for impl-verifier / impl-critic

1. **app.py monkeypatch** is the highest-risk change. The fix (patching both
   `pia.post_json` and `_core_bp.post_json`) was validated by the canary going
   from 21/23 → 23/23. The reviewer should confirm the restore path in the
   finally block restores both.

2. **AIMD coefficients**: the four AIMD constants (`MIN_CHUNK_SPINS=500`,
   `SUCCESS_STREAK_FOR_GROW=1`, `CHUNK_SPINS_GROWTH=1.25`, `CIRCUIT_PAUSE_S=3.0`)
   are byte-identical between PIA-original and `base_pipeline.py`. The
   test_analyzer_core_base_pipeline.py C8 tests pin these values.

3. **`DEFAULT_GUIDELINE_RULES_PATH` path computation**: recomputed from
   `base_pipeline.py`'s location using `parents[3]` (project root) instead of
   PIA's `parents[1]`. Verified to resolve to the same absolute path as PIA's
   original computation, and confirmed `exists() = True`.
