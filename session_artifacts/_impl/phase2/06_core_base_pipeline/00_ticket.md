# Ticket P2-B4 — Carve `analyzer/core/base_pipeline.py` (helpers only; main() stays in PIA)

> Phase 2 / Wave 2b fourth and final carve. **MEDIUM risk** — 8 helper
> functions (~700 lines total) move into a new `core/base_pipeline.py`.
> `main()` itself stays in PIA for now; the "thin shim" goal in §5.8 will
> be reached naturally across Wave 2c-2f when feature extraction forces
> the orchestration to flatten.

---

## §1 Ticket scope

8 helper functions move out of `fresh_slotlab/player_impact_analyzer.py`
(PIA) into a new `fresh_slotlab/analyzer/core/base_pipeline.py`:

| PIA line | Symbol                          | Approx LOC | Notes                                |
|----------|---------------------------------|------------|--------------------------------------|
| 294      | `parse_args`                    | ~145       | argparse setup, no external state    |
| 439      | `post_json`                     | ~85        | HTTP layer (urllib + json)           |
| 525      | `_classify_failure`             | ~70        | error string -> failure class enum   |
| 987      | `aimd_tune`                     | ~40        | AIMD concurrency tuning              |
| 1028     | `post_json_with_retry`          | ~70        | retry wrapper around `post_json`     |
| 1160     | `select_replay_chunks_by_md5`   | ~75        | resume-from-cache picker             |
| 1277     | `make_payload`                  | ~80        | request body builder                 |
| 1392     | `run_sampling_chunk`            | ~75        | one-chunk fetch loop wrapper         |

Plus the module-level constants these consume:
- `ENDPOINT_URL` / `DEFAULT_ENDPOINT_URL` (PIA line ~214)
- `MAX_PAYLOAD_LOG_BYTES` if applicable

**Strategy**: a single carved module that exposes the HTTP layer + the
chunk-sampling orchestrator. Tests against M14 mode 1 cached fixture
keep going through PIA's main() (which calls these via the re-export).

**Out of scope** (stays in PIA, deferred to Wave 2c-2f):
- `main()` body refactor itself (~3964 lines). The 200-line markdown-report
  block in main() will move when the feature ABC pipeline lands per §6.2
  deliverable 2.
- `_load_bcm_pairings`, `_infer_feature_spin_type_mapping`,
  `_resolve_bonus_feature`, `collect_feature_match_warning`,
  `build_cycle_observation`, `ci_halfwidth_pp`, `safe_div`, `append_jsonl`,
  `compute_analyzer_version` — these are intermixed helpers; they will be
  carved when their owning feature pipelines land in Wave 2c-2e.

---

## §2 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 1`
  — "Carve core/ (4 files)"; base_pipeline.py is the fourth.
- `session_artifacts/_arch/04_architecture_proposal_v5.md §5.8` — "`pia.main`
  stays as thin orchestrator". This ticket does NOT achieve the thin-shim
  goal directly; Wave 2c-2f will finish that arc.
- `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` Wave 2b row P2-B4 —
  8-function list.
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — the
  new module must be import-safe; no module-top I/O.
- Memory `feedback_upstream_throttle_ceiling.md` — `aimd_tune` is the
  throttle governor; its behavior must not drift (the upstream per-IP
  rate limit makes drift expensive to detect).
- Memory `feedback_perf_claim_needs_e2e_event_stream.md` — the P1-A1
  canary is the e2e proof; HTTP layer changes are exactly the kind of
  thing the canary catches.

---

## §3 Contract (testable invariants)

### C1 — Files exist + symbols carved
- `fresh_slotlab/analyzer/core/base_pipeline.py` present with the 8
  functions listed in §1.
- PIA re-exports the 8 symbols via the existing dual-path import block.
- `pia.parse_args is core_base_pipeline.parse_args` (and same for the
  other 7).

### C2 — P1-A1 3-invocation parity canary stays GREEN
`tests/integration/test_analyzer_three_invocation_parity.py` 23/23
GREEN. This is the gold standard — the HTTP layer + sampling loop are
exactly what the canary stresses by running 3 invocation paths against
M14 mode 1 cached fixture.

### C3 — `ENDPOINT_URL` mutability preserved
PIA's `main()` does `global ENDPOINT_URL; if args.endpoint_url:
ENDPOINT_URL = args.endpoint_url`. After the carve, the module-level
`ENDPOINT_URL` must still be mutable at runtime (writable by main() AND
read by post_json). Pick ONE strategy and document:
- **Option A**: keep `ENDPOINT_URL` in PIA; pass it as an argument to
  every `post_json` call.
- **Option B**: move `ENDPOINT_URL` to `core/base_pipeline.py`; PIA's
  main() mutates `core_base_pipeline.ENDPOINT_URL` via setattr.

Option A is cleaner (no module-global mutation at all) but requires
touching every callsite. Option B preserves the existing pattern with
one indirection. Implementer's choice; document in `02_implementation.md`.

### C4 — Subprocess import safety
`python -c "import fresh_slotlab.analyzer.core.base_pipeline"` rc=0 no
stderr.

### C5 — Cycle freedom
- `base_pipeline.py` MUST NOT import from `player_impact_analyzer.py`.
- `base_pipeline.py` MAY import from `core/parser.py`,
  `core/_utils.py`, `core/aggregator.py`, `core/writer.py`. (All are
  upstream of base_pipeline in the data flow.)
- `core/parser.py`, `core/aggregator.py`, `core/writer.py` MUST NOT
  import from `core/base_pipeline.py` (wrong direction).

### C6 — Hash composition rolls forward
`compute_base_analyzer_version()` hashes `core/*.py`. Adding
`base_pipeline.py` flips the base hash deterministically. Gate test on
the function being exported through versioning.py (currently skipped
per P2-B1b/B2/B3 critic notes).

### C7 — All existing tests pass
- 8-suite Phase 1+2 regression (P1-A1 canary, P1-B1, P1-A2, P2-A1,
  P2-A2, P2-B1a/b, P2-B2, P2-B3): 519+ GREEN.
- New `tests/backend/test_analyzer_core_base_pipeline.py` (~30+ tests).

### C8 — Inject-bug TDD
- Inject: change AIMD growth factor from 1.1 to 0.5 → next-chunk
  concurrency stops growing → canary may still pass but a unit test on
  `aimd_tune` catches it directly.
- Inject: change retry count default → `post_json_with_retry` test
  RED.
- Inject: change `select_replay_chunks_by_md5` selection criterion →
  cache-resume integration test RED. (May not have such a test; OK to
  skip the inject and document.)

---

## §4 Out of scope

- main() body refactor (Wave 2c-2f).
- Feature ABC pipeline (Wave 2c).
- 9 other helpers listed in §1 "Out of scope" sub-bullet.
- Frontend.
- Removing legacy `compute_analyzer_version`.

---

## §5 Rollback path

Single commit. `git revert <sha>` restores PIA's 8 functions; deletes
`base_pipeline.py`.

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM.

1. **ENDPOINT_URL global mutability.** PIA writes to it (main(), line
   1470), the HTTP layer reads from it (post_json). The carve must
   preserve this pattern OR refactor it. The cleanest path is dependency
   injection (pass endpoint_url to post_json), but it touches every call
   site. The pragmatic path is keeping it module-global; pick one and
   document.

2. **AIMD throttle governor.** Memory `feedback_upstream_throttle_ceiling.md`
   warns that drift in `aimd_tune` triggers per-IP rate limits that take
   hours to recover. The carve must preserve `aimd_tune`'s
   growth/decrement formula byte-for-byte. The implementer should NOT
   refactor any AIMD logic.

3. **`post_json_with_retry` retry semantics.** The retry count, backoff
   strategy, and which errors are retried must all preserve exactly.
   The function is consumed by `run_sampling_chunk` in a tight loop;
   one off-by-one in the retry counter is the difference between a
   self-recovering run and a flapping run.

4. **Cycle risk via `make_payload`.** `make_payload` may call helpers
   that stay in PIA (e.g. `_lookup_machine_md5`, `compute_effective_analyzer_version`
   from P2-A1, or others). Implementer must:
   - Move it cleanly with all its dependencies importable from
     core/* or pass them as args.
   - Verify no back-import to PIA via the same cycle-grep test as
     prior tickets.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — create `core/base_pipeline.py` with the 8
  functions. Move bodies verbatim. Add re-exports to PIA dual-path
  import block. Update `main()`'s `global ENDPOINT_URL` callsite per
  the chosen strategy in §3 C3. Run pytest before claiming pass.

- `impl-tester` — write `tests/backend/test_analyzer_core_base_pipeline.py`
  covering C1-C8. Focus on AIMD invariants, retry counts, payload
  builder schema. Inject-bug for each.

### Wave 2 (parallel)
- `impl-verifier` — P1-A1 canary + 8-suite regression + subprocess
  smoke + cycle grep. Specifically verify ENDPOINT_URL still works
  end-to-end (the canary may not exercise --endpoint-url; add a small
  test that sets it and asserts post_json reads the new value).
- `impl-critic` — adversarial: did the AIMD coefficients drift? Did
  retry semantics change? Is the ENDPOINT_URL strategy documented and
  tested? Was a back-import quietly introduced via make_payload?

Expected wall time: ~80-120 min. Comparable to P2-B1b; smaller surface
than P2-B2 but more semantically-risky helpers (AIMD, retry).
